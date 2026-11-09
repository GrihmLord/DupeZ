# Native runtime containment — 2026-10-24

## Status and scope

Containment changes are recorded at code checkpoint
`1db32d750ee1a1b23733ff38f6b53fdad8957d7f`. Fresh GPU/Compat builds and offline
final-artifact observations passed; GPU maintenance-only checks passed for both
unchanged and recipient-modified builds. This document does
not approve a release, declare native vulnerability freedom, or establish
complete corresponding source. No browser, packet engine, or game workflow was
launched during this review.

The embedded browser remains disabled: its exact reviewed native-combination
table is intentionally empty. A higher Qt version alone cannot enable it.
Billing availability does not change this security decision.

## Measured baseline: ambient native dependencies

The diagnostic baseline's
`build/recipient-evidence-20261024/baseline-work/gpu/dupez_gpu/Analysis-00.toc`
contains **48 native entries from unrelated application-runtime directories**:
four from Poppler (the `libssl-3-x64.dll` / `libcrypto-3-x64.dll` pair and
`icuuc.dll` / `icudt78.dll`), and 44 libheif-sourced UCRT/API-set entries.
These were outside the locked build environment, verified CPython installation,
Windows System32, and exact managed-binary inputs. The count describes raw
Analysis entries, not 48 distinct vulnerabilities or the final packaged count.
The baseline executable is diagnostic-only and was not launched.

A separate source-environment, renderer-free Qt TLS probe reported active
OpenSSL **3.6.4**, with loaded-library inspection locating the Poppler copy.
Python's `ssl` reported **3.5.9**, while cryptography reported its own
**4.0.3** backend. Those are separate native consumers: the patched Python copy
did not establish that Qt was using patched OpenSSL. OpenSSL's
[2026-09-29 advisory](https://openssl-library.org/news/secadv/20260929.txt)
lists 3.6.5, 3.5.9, and 4.0.3 as fixes on their respective branches, including
CVE-2026-84782. No claim is made that every listed issue was reachable here.

This collection mechanism is consistent with the pinned
[PyInstaller 6.22.2 Qt hook](https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.22.2/PyInstaller/utils/hooks/qt/__init__.py):
it probes Qt's OpenSSL backend and searches for matching dynamic libraries.
Qt itself [prefers OpenSSL when available, otherwise Schannel on Windows](https://doc.qt.io/qt-6.11/qsslsocket.html#activeBackend).
Dependency lock hashes alone therefore did not constrain the actual native graph.

## Implemented containment

- `packaging/native_runtime_policy.py` restricts the build process's DLL search
  PATH to the build interpreter, verified base Python/DLLs, and the Windows
  system directory obtained through WinAPI. Inherited Qt/QML/WebEngine path
  overrides are removed from this build process; host settings are not changed.
- `packaging/hooks/hook-PyQt6.QtNetwork.py` avoids the ambient OpenSSL probe and
  retains only the Qt Schannel TLS plugin. Final collection rejects unreviewed
  TLS plugins and noncanonical OpenSSL sources. CPython's `libssl-3.dll` and
  `libcrypto-3.dll` remain required; cryptography's internal backend is untouched.
- `packaging/build_common.py` rejects every final native Analysis entry outside
  the explicit roots or individually verified managed snapshots, then records
  destination, origin, and SHA-256 in generated `native-binaries.json`.
  Repository, home, and temporary directories are not broad allowlisted roots.
- `scripts/native_build_evidence.py` compares final CArchive native destinations
  and bytes against that manifest, current approved sources, and managed source
  pins. It rejects unexpected native payloads and forbidden TLS components;
  public summaries contain counts and hashes, not absolute source paths. The
  PyInstaller reader is for these local builds, not a bounded hostile-archive
  parser. Windows type-`b` entries can also be ordinary data, so the inspector
  checks recorded natives, native suffixes, and additional MZ signatures.
- `dupez.py --verify-native-tls` supplies a separate maintenance probe requiring
  Schannel as the only available and active Qt TLS backend. It creates no socket,
  GUI, renderer, or event loop and does not switch backends to manufacture a pass.
  The clean and modified GPU artifacts passed this probe with standard-user
  tokens and exit 0. Compat was inspected offline, not executed.
- `app/gui/map_host/security_policy.py` keeps token, sandbox, flag, and version
  prerequisites, then requires an explicitly reviewed exact native combination.
  It also rejects browser executable/resource/locale overrides, which Qt
  [documents as selecting separate runtime files](https://doc.qt.io/qt-6.11/qtwebengine-deploying.html).
- Imported account notes, holdings, status text, deletion prompts, and preset
  descriptions now use plain text. Stats-panel dynamic values are escaped while
  intentional application markup remains. This reduces unintended rich-text
  parsing; it is not a Qt parser patch. See Qt's
  [QLabel input warning](https://doc.qt.io/qt-6/qlabel.html#textFormat-prop) and
  [QTextEdit rich-text control](https://doc.qt.io/qt-6/qtextedit.html#acceptRichText-prop).

## Remaining upstream and native-review blockers

As checked on 2026-10-24, PyPI still lists Windows x86-64 native wheels
`pyqt6_qt6-6.11.2-py3-none-win_amd64.whl` and
`pyqt6_webengine_qt6-6.11.2-py3-none-win_amd64.whl` as the latest releases.
A reviewed patched replacement was not available through this pinned wheel
route. Qt's upstream release availability is not equivalent to matching PyQt
wheel availability. Sources: [PyQt6-Qt6](https://pypi.org/project/PyQt6-Qt6/),
[PyQt6-WebEngine-Qt6](https://pypi.org/project/PyQt6-WebEngine-Qt6/).

| Advisory / surface | Relevant upstream remedy | Status of installed Qt 6.11.2 |
| --- | --- | --- |
| [CVE-2026-95620](https://www.qt.io/blog/security-advisory-cve-2026-95620), Qt Network HTTP/2 use-after-free | Patch or Qt 6.11.3/6.12; disable HTTP/2 per affected request as mitigation | In affected range; Schannel does not patch HTTP/2 |
| [CVE-2026-96432](https://www.qt.io/blog/security-advisory-cve-2026-96432), HTTP/2 null dereference | Patch or Qt 6.11.3; disable HTTP/2 per request as mitigation | In affected range |
| [CVE-2026-101201](https://www.qt.io/blog/security-advisory-cve-2026-101201), Qt JSON / Qt5 compatibility parsing | Patch or Qt 6.11.3; advisory lists no mitigation | In affected version range; exact module/call-path applicability still requires review |
| [CVE-2026-105923](https://www.qt.io/blog/security-advisory-cve-2026-105923), VectorImage SVG parsing | Patch or Qt 6.11.3/6.12; avoid untrusted VectorImage SVG input | In affected range; not evidence that DupeZ invokes that QML path |
| [CVE-2026-15037](https://www.qt.io/blog/security-advisory-cve-2026-15037-xml-injection), QDom XML serialization | Qt 6.12 changes the default; earlier versions require safe invalid-data policy and null checks | Existing default remains affected if this API is used |
| [CVE-2026-16762](https://www.qt.io/blog/cve-2026-16762), QXmlStreamReader CPU denial of service | Qt 6.11.2 or upstream patch | Installed version reaches this advisory's fixed version; not an unresolved 6.11.3 blocker |

The installed Qt WebEngine security-version probe reported
**151.0.7922.71**. Chrome subsequently shipped **151.0.7922.173/.174** with
security fixes including V8, DOM, and Network issues. This demonstrates that the
installed number alone is not current clearance; it does **not** establish that
every Chrome CVE applies to this Qt build. Exact Qt backport/artifact mapping and
sandbox evidence remain required before approving any combination. See the
[Chrome team's 2026-08-20 release](https://chromereleases.googleblog.com/2026/08/stable-channel-update-for-desktop_0404570826.html).

Direct application searches did not find use of several affected high-level
Qt APIs. Absence of a direct Python reference does not prove absence of native,
plugin, transitive, or imported-data reachability. No version-floor waiver was
made on that basis. Schannel containment also does not patch Chromium/BoringSSL,
Qt JSON/XML/image parsing, or arbitrary bundled DLLs. OS patch status, full native
dependency/backport review, driver ABI/behavior, and exact-source completeness
remain separate verification obligations.

## Completed local exact-build observations and remaining limits

Machine-readable hashes, source identity, input changes, exit observations and
limitations are recorded in
[`recipient-rebuild-2026-10-24.json`](../../packaging/license-evidence/recipient-rebuild-2026-10-24.json).
These are operator observations, not independently authenticated attestations.

| Evidence | Current status / fields to record |
| --- | --- |
| Exact-source rebuild | PASS locally — clean GPU and Compat, plus modified GPU, built from checkpoint `1db32d7` in fresh outputs with isolated CPython 3.13.17 and hash-pinned inputs; no production keys |
| Final native inventory | PASS for all three artifacts — 259 native entries each: 231 locked-venv, 24 verified-base-Python, 4 managed native; no ambient source origins; actual CArchive bytes match the recorded hashes and source pins |
| Qt TLS maintenance observation | PASS on clean and modified GPU — standard-user, exit 0, available/active backend only Schannel, SSL support true; Compat runtime remains untested |
| Recipient rebuild evidence | PASS for the limited application + zeroconf Python-layer demonstration — actual runtime markers observed; native Qt/Cython/driver rebuild and bit-for-bit reproduction are not claimed |
| Release/security disposition | NOT APPROVED by this audit — current native combination remains denied regardless of successful containment checks |

The exact-checkpoint regression suite passed **3,270 tests**, with **10 skips**
(six opt-in hardware cases, four missing symlink privileges), **58.28%** app
coverage, in **238.47 seconds**. Source and frozen-dependency preflights pass.
The licensing and complete-source readiness gates still fail intentionally.
No GUI, renderer, hardware/driver lifecycle, installer, or Compat administrator
runtime pass is inferred. The earlier contaminated diagnostic executable was
not launched or promoted into this evidence.
