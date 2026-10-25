# Qt native review — 2026-10-25

This review preserves the verified Qt 6.11.2 baseline and identifies a separate
Qt 6.11.3 installer candidate. It does not clear the native security gate, change
runtime locks, approve licensing, or establish complete corresponding source.
Machine-readable pins and observations are in
[`qt-native-review-2026-10-25.json`](../../packaging/license-evidence/qt-native-review-2026-10-25.json).
The baseline repository checkpoint is `6fa81f48b1c96c949abe27b4822805914d128e78`.

## Availability and a usable candidate route

The public PyPI metadata still lists `PyQt6-Qt6` and `PyQt6-WebEngine-Qt6`
6.11.2, with bindings at 6.11.0. Existing PyQt6 metadata requires native Qt
`>=6.11.0,<6.12.0`; changing a main lock to Qt 6.12 would not be a normal
compatible dependency update. Exact Windows wheel hashes and upload dates are
recorded in the JSON. Sources: [Qt wheel metadata](https://pypi.org/pypi/PyQt6-Qt6/json),
[WebEngine wheel metadata](https://pypi.org/pypi/PyQt6-WebEngine-Qt6/json),
[binding metadata](https://pypi.org/pypi/PyQt6/json).

The ordinary [6.11 source release directory](https://download.qt.io/official_releases/qt/6.11/)
has 6.11.2 but no 6.11.3 subdirectory at this observation. However, Qt's
[public Windows installer metadata](https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6113/qt6_6113_msvc2022_64/Updates.xml)
publishes `6.11.3-0-202610220312`, dated 2026-10-22, with
[matching source package metadata](https://download.qt.io/online/qtsdkrepository/all_os/qt/qt6_6113_unix_line_endings_src/Updates.xml).
Public installer availability is therefore real, but is recorded separately
from final-release availability and approval.

Qtbase, QtSvg and Qt5Compat binary archives and their matching source archives
were downloaded into ignored `build/qt-native-review-20261025/`, with individual
size limits and equality checks against Qt-published SHA256 values. The archive
review did not execute native payloads; a subsequent isolated probe is recorded
below. The three binary
archives are a subset, not a complete replacement for `PyQt6-Qt6`.

[Riverbank's supported bundling workflow](https://pyqt-builder.readthedocs.io/en/latest/pyqtbundle.html)
accepts a Qt Company binary installation. It can omit bindings and bundle a newer
Qt; `QAxContainer` is an explicit ABI exception and must be excluded when retaining
the 6.11.0 binding. Source-built Qt is unsupported by that bundling command. A
separate stripped candidate can retain Core, Gui, Network, Widgets, OpenGL,
OpenGLWidgets, PrintSupport, Svg, SvgWidgets and Test, with explicit checks for
the matching plugins, helper DLLs and MSVC runtime. The reviewed main locks remain
unchanged.

## Isolated runtime proof

The supported `pyqt-bundle` command produced a 31,640,559-byte candidate wheel:

```text
build/qt-native-review-20261025/candidate-wheel-v3/
  PyQt6-6.11.0-6.11.3dupezcandidate-cp310-abi3-win_amd64.whl
SHA256 faa3e693d4fb57188784799fd54a9de49f737ea0638c35e09cceb6db6be07d30
```

The independent candidate venv passed `pip check` and an offline probe as a
standard user. All ten retained bindings imported, the runtime reported Qt
6.11.3, an offscreen widget initialized, a trusted SVG rendered correctly, and
Schannel became the active SSL backend. Every loaded Qt DLL resolved inside
that candidate venv. WebEngine was absent from the loaded module list. This
does not test a real TLS connection, OpenGL context, full application or frozen
executable.

The recipe and all input pins are retained in the evidence JSON. The official
builder was installed offline from hash-locked wheels into a separate builder
venv. Important reproducibility details are:

1. Use Qt's directory layout `6.11.3/msvc2022_64` and put the two verified QtGui
   helper DLLs in its `bin` directory.
2. Pass the original PyPI binding bytes under the canonical filename
   `PyQt6-6.11.0-cp310-abi3-win_amd64.whl`. PyQt-builder 1.20.1's case-sensitive
   metadata check otherwise retains the external `PyQt6-Qt6` requirement when
   the input filename is lowercase. No wheel contents were manually edited.
3. Use the retained/excluded module lists in the JSON with `--no-msvc-runtime`,
   `--no-openssl` and `--build-tag-suffix dupezcandidate`. No
   `--ignore-missing` bypass was used.
4. Install the resulting wheel plus pinned `PyQt6-sip==13.11.1` into a fresh
   venv. The local probe used the host's Microsoft runtime in System32,
   version `14.51.36247.0`; that is not a public redistribution receipt.

Full image-format plugin and translation parity has not been established. The
Qt-provided software OpenGL helper remains Mesa 11.2.2 and requires separate
source/security review. The new wheel is a review candidate, not a substitute
for the complete PyPI wheel's supported module inventory.

## Recipient preparation

The tracked [`prepare_qt_candidate.py`](../../scripts/prepare_qt_candidate.py)
uses [`qt-candidate-inputs.json`](../../packaging/qt-candidate-inputs.json), with
12 pinned inputs totaling 116,873,486 bytes. Run it with the reviewed Windows x64
Python 3.13 interpreter from the checkout root:

```powershell
python -I scripts/prepare_qt_candidate.py --output build/qt-candidate-review --install-runtime
```

`--download-only` retains verified inputs without invoking the bundler.
`--cache <directory>` reads matching input filenames from a verified cache;
existing cache entries with a wrong hash fail rather than falling back to the
network. The output directory must be new and below the checkout's `build/`.
The script validates canonical versions, allowed module names and complete
manifest schemas before constructing paths or commands. Receipts hash the exact
manifest bytes parsed before downloads. It bounds downloads and archive expansion, checks the exact reviewed
7z member listings, rejects links/unsafe paths and cross-archive overlays,
checks unresolved ancestors for junctions, and never runs archive scripts
or Qt native executables. The only third-party code invoked during preparation
is the pinned Python bundler and its pinned tooling in a new venv. Children use
isolated Python and a minimal OS-derived environment with a private profile and
temporary directory; parent credentials, proxies and pip configuration are not
inherited. The runtime
option installs into another venv and runs `pip check`; it does not launch Qt.

The focused workflow tests passed **51/51**. An end-to-end run from the verified
local cache produced and installed a second candidate with `pip check` passing.
All **933 wheel member payloads** matched the independently prepared candidate.
The ZIP hashes differed, so this is content equivalence rather than a claim of
bit-for-bit reproducibility. Exact receipts are in the evidence JSON.

Production integration still requires coordinated changes to
`requirements.in`, `requirements-locked.txt`, the third-party inventory,
source inputs and license/SBOM evidence. The current lock requires separate
`PyQt6-Qt6`, `PyQt6-WebEngine` and `PyQt6-WebEngine-Qt6` distributions;
`scripts/license_payload.py` correctly checks those installed identities and
versions. The bundled candidate does not create those distribution identities.
Do not fabricate their metadata or overlay Qt 6.11.2 DLLs onto this candidate.

## Source correspondence gained, and its limits

The 6.11.3 installer archives contain binary SPDX JSON, source SPDX inventories,
and configuration metadata. Qtbase reports MSVC `19.44.35227`, CMake `4.3.2`,
shared debug/release builds and Schannel support. These receipts are stronger
than matching only a package version.

The source archive files were compared with the source SPDX records shipped
inside those exact SHA256-verified binary archives. Raw or Windows CRLF-normalized
SHA1 inventory matches were:

| Module | Matching files | Other observations |
| --- | ---: | --- |
| Qtbase | 22,498 | `.tag` differs; 36 Git metadata files are absent from the tarball |
| QtSvg | 628 | `.tag` differs; 9 Git metadata files are absent from the tarball |
| Qt5Compat | 1,411 | All source SPDX records matched |

Archive files outside the source SPDX inventory, including license, generated,
REUSE and test inputs, are counted separately. Qtbase's binary SPDX references
`b21f6a785516e898388cda2fe5d3e7dacd6d4b7d`, while its source tarball `.tag` is
`138f955f0b5e50e4a6c2ee1e78a2279db52ae9e3`. This discrepancy remains explicit;
the file correlation does not erase it. SHA1 is used only to correlate the
upstream inventory. Archive trust checks use SHA256. Neither comparison is an
independent native rebuild or proof that every build input has been supplied.

The retained 6.11.2 WebEngine source archive also has useful exact members:
`.tag` is `a33fa2a897e5ee58e385b3f88dc247d99fca56db`; `CHROMIUM_VERSION`
declares base `140.0.7339.264` and security patches through `151.0.7922.71`,
consistent with the earlier runtime probe. Its inner Chromium `chrome/VERSION`
instead ends in patch `225`; it must not be substituted for the Qt security
patch declaration. This closes a declaration-to-source-member gap, not all
Chromium backport, GN/CMake, transitive-source or binary-build gaps.

## Security applicability

Official patch bytes are pinned as non-executed review inputs. Reverse patch
checks inspect source contents only and do not apply changes to native binaries.

| Advisory | Qt 6.11.2 baseline | 6.11.3 candidate source evidence |
| --- | --- | --- |
| [CVE-2026-95620](https://www.qt.io/blog/security-advisory-cve-2026-95620), HTTP/2 lifetime | Affected version; upstream offers per-request HTTP/2 disablement | Production reverse check passes; full check encounters changed test context |
| [CVE-2026-96432](https://www.qt.io/blog/security-advisory-cve-2026-96432), HTTP/2 null dereference | Affected version | Full and production reverse checks pass |
| [CVE-2026-105923](https://www.qt.io/blog/security-advisory-cve-2026-105923), triangulator via VectorImage | Affected version; reachability requires separate evidence | Full and production reverse checks pass |
| [CVE-2026-101201](https://www.qt.io/blog/security-advisory-cve-2026-101201), binary JSON | Qt6 patch paths are in `qt5compat/src/core5/serialization/qbinaryjson.cpp` | Overflow check and both `size_t` comparisons are present; the second patch supersedes the first patch's context |
| [CVE-2026-82292 official patch](https://download.qt.io/official_releases/qt/6.11/CVE-2026-82292-qtbase-6.11.diff.mirrorlist), QDom null handling | Review before introducing `ReturnNullNode` policy | Full and production reverse checks pass |
| [CVE-2026-15037](https://www.qt.io/blog/security-advisory-cve-2026-15037-xml-injection), QDom serialization | Unsafe default remains a conditional exposure | 6.11.3 does not provide Qt 6.12's default change |

The 6.11.2 baseline venv contains no `*Compat*.dll`. This is recorded as
component absence only. It does not turn the advisory's broad historical Qt Core
wording into proof of global non-exploitability, nor substitute for final
CArchive inspection. The 6.11.3 Qt5Compat download is a review input and does not
add that module to the application.

Other reviewed advisories explicitly name 6.11.2 as fixed, including
[SVG recursion CVE-2026-8168](https://www.qt.io/blog/security-advisory-cve-2026-8168),
[HTTP cache parsing CVE-2026-76151](https://www.qt.io/blog/security-advisory-cve-2026-76151),
[XML element recursion CVE-2026-78253](https://www.qt.io/blog/security-advisory-cve-2026-78253),
[Qt Quick path parsing CVE-2026-79616](https://www.qt.io/blog/security-advisory-cve-2026-79616),
and [XML stream parsing CVE-2026-16762](https://www.qt.io/blog/cve-2026-16762).
These are version-level assessments, not independent binary reproduction.

## Remaining work without GitHub billing

The isolated candidate wheel/import experiment completed independently of CI
billing. Before adopting it, finish the complete module/plugin inventory;
verify Schannel-only TLS handshakes and full GUI behavior; rerun focused and
full tests; rebuild both variants and recipient artifacts;
then update the source-delivery inventory and exact build evidence together.
Do not enable WebEngine merely because Qtbase was upgraded.

A native source build is a separate route. The installed VS Build Tools instance
has no MSVC C++ tools, bundled CMake or Ninja. The installed Windows SDK headers
are `10.0.19041.0`; [WebEngine's requirements](https://doc.qt.io/qt-6.11/qtwebengine-platform-notes.html)
include SDK `10.0.26100.0` or newer and MSVC 14.36 or newer for VS2022.
No toolchain was installed and no source build was started. Exact source-specific
build requirements and every compiler/helper input must be pinned first.

[Qt's separate WebEngine release plan](https://www.qt.io/blog/qt-webengine-will-release-separate)
also means a future Qt 6.12 update cannot stand in for a Chromium security review:
WebEngine and QtPdf acquire separate versioning. Native patching, exact source
correspondence, licensing approvals and blocked GitHub checks remain distinct
release requirements.
