# Qt candidate validation — November 1, 2026

The isolated Qt 6.11.3 candidate now has an enforced native inventory, nine
approved image-format plugins, 33 Qtbase translation catalogs, and successful
local Schannel handshakes. Two preparations produced identical restricted
wheel bytes. **The production runtime remains Qt 6.11.2.** Production dependency
locks, distribution identities, source-delivery decisions and release approval
have not changed.

The baseline checkpoint for this continuation is
`af461cbc899cf146d3d9808496a5806d75cb2528`. Exact input URLs, sizes, SHA256 pins,
native member hashes, source observations and TLS results are retained in
[`qt-candidate-validation-2026-11-01.json`](../../packaging/license-evidence/qt-candidate-validation-2026-11-01.json).
This continues the [October 25 Qt review](QT_NATIVE_REVIEW_2026-10-25.md);
it does not replace its outstanding native/source limitations.

## Reproducible candidate preparation

The tracked [preparer](../../scripts/prepare_qt_candidate.py) consumes schema
`dupez.qt-candidate-inputs.v2` and emits
`dupez.qt-candidate-preparation.v2`. The
[manifest](../../packaging/qt-candidate-inputs.json) now pins **16 inputs totaling
123,517,354 bytes**. Four additions provide matching Qt 6.11.3 image-format and
translation binary/source archives. Their membership in Qt's
[Windows installer metadata](https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6113/qt6_6113_msvc2022_64/Updates.xml)
and [source metadata](https://download.qt.io/online/qtsdkrepository/all_os/qt/qt6_6113_unix_line_endings_src/Updates.xml)
was checked at installer revision `6.11.3-0-202610220312`, with published
archive sizes and SHA256 values independently checked before use.

Run with the reviewed Windows x64 CPython 3.13 interpreter from the checkout:

```powershell
python -I scripts/prepare_qt_candidate.py --output build/qt-candidate-review --install-runtime
```

The output directory must be new. `--cache` reads already verified input files;
`--download-only` performs acquisition without bundling. Archive expansion,
paths, case collisions, links and cross-archive overlays remain checked.
Preparation uses fresh builder/runtime environments and a minimal child
environment without inherited credentials, proxies or pip configuration.
Qt archive scripts and native executables are not run during preparation.
The optional installation runs `pip check`; separate runtime tests follow.

The final observed preparation is retained under
`build/qt-candidate-parity-final-20261101/`. Its restricted wheel is:

```text
PyQt6-6.11.0-6.11.3dupezcandidate-cp310-abi3-win_amd64.whl
30,238,609 bytes
SHA256 5ae71fb933f4cafeaba3eac2d98a35ece588950ea34d3fa5e0252cbc811b29a9
```

The earlier preparation under `build/qt-candidate-parity-reviewed-20261101/`
produced the same complete wheel bytes. Both used the same pinned input cache;
this establishes local recipe reproduction, not an independent native
source compilation or reproduction on another host. The evidence records
the exact workspace script/manifest bytes consumed and separate LF-normalized
serialization digests. Normalized digests do not substitute for observed inputs.

## What the inventory checks fixed

Inspection found that the pinned Riverbank bundler's `--exclude` option omitted
native Qt libraries while leaving the original excluded `.pyd` bindings in the
wheel. Likewise, `--no-openssl` omitted OpenSSL libraries but left OpenSSL and
certificate-only backend plugins. SQL plugins also remained despite excluding
QtSql. The earlier observation that Schannel was active did not establish a
Schannel-only candidate payload.

The preparer still uses [Riverbank's bundling workflow](https://pyqt-builder.readthedocs.io/en/latest/pyqtbundle.html),
then derives a restricted review wheel with a regenerated
[standard wheel RECORD](https://packaging.python.org/en/latest/specifications/binary-distribution-format/).
Both the unrestricted bundler artifact and derived artifact are retained and
hashed. All **578 removed members** are listed in the preparation receipt.
Every retained member other than RECORD is byte-identical to the bundler output,
including METADATA, WHEEL and license files. No distribution identity or external
Qt dependency is fabricated to satisfy installation checks.

The derived wheel must contain exactly:

| Payload | Verified inventory |
| --- | --- |
| Binding extensions | 10: Core, Gui, Network, Widgets, OpenGL, OpenGLWidgets, PrintSupport, Svg, SvgWidgets, Test |
| Native libraries | 10 matching Qt libraries plus `d3dcompiler_47.dll` and `opengl32sw.dll` |
| Plugins | 17, including nine approved image plugins and only `qschannelbackend.dll` for TLS |
| Translations | 33 `qtbase_*.qm` catalogs |
| Total | 39 native members; 586 wheel members |

Missing or unexpected native files, unexpected distribution roots, external Qt
dependencies, incomplete RECORD coverage, altered hashes, disabled module data,
and browser/QML payload fail validation. The manifest cannot re-enable excluded
bindings. The nine image plugins are GIF, ICNS, ICO, JPEG, SVG, TGA, TIFF, WBMP
and WebP. The baseline's additional PDF plugin is intentionally omitted together
with QtPdf and Chromium. These are inventory checks, not exhaustive decoder tests.

The first stricter preparation caught an upstream Windows-specific RECORD issue:
the bundler's unhashed self-reference used a backslash while the ZIP member used
a slash. Only that exact unhashed self-reference is canonicalized. Other payload
paths receive no separator exception. The pinned bundler's CRCRLF metadata
line endings are normalized only while parsing; stored metadata bytes remain
unchanged. These cases have dedicated regressions.

The focused preparer suite passed **70 tests**, Ruff passed, and fresh candidate
installation passed `pip check`. The candidate-compatible application suite at
test checkpoint `b59f982` passed **3,445 tests**, with 18 expected skips. Eight
skips explicitly require absent browser bindings; the other ten cover hardware
opt-ins and unavailable symlink privileges. Two modules that import WebEngine
were excluded: `test_map_request_policy.py` and `test_codeql_remediation.py`.
The full production-dependency suite covers those modules and passed **3,501
tests**, with ten skips; 139 affected production tests passed after test-only
isolation changes.

The first completed candidate run retained four failures: three browser-only
assumptions and an idempotence fixture's filesystem journal error. Narrow
dependency declarations and a mock journal for that unit fixture preceded the
passing rerun. These results do not claim candidate frozen-runtime coverage.
The final preparation consumed exactly the 9,760-byte manifest published at
`dbf4d62`; workspace and Git blob bytes and the preparation digest match.

## Added source correspondence

The two new modules were independently inspected against their pinned binary
archives. No native payload was executed for this comparison.

For **QtImageFormats**, all **552 source-SPDX entries** matched the source
archive: 139 raw matches and 413 after CRLF normalization. There were no missing
inventory files or mismatches; 12 additional license/REUSE files were recorded.
Source and binary attribution agree on libtiff 4.7.2 and libwebp 1.6.0. The source
declares Qt 6.11.3 while retaining an `alpha1` prerelease configuration field;
the installer candidate is not promoted to final-release approval by this review.

The ten release/debug DLL records did not match the raw signed-file SHA1 values
in binary SPDX. All ten matched after removing the end-of-file certificate table
and zeroing only the PE checksum/security-directory fields **in memory**.
The original signed bytes separately matched the pinned archive members. No
modified DLL was written or executed. This is a precise correlation with the
upstream pre-signing inventory, not a claim that the raw file hashes matched.
Only five release DLLs from this module enter the restricted wheel.

For **QtTranslations**, all **315 unique binary paths** matched the 630 SPDX
records. The archive has no source SPDX inventory. Of 314 compiled `.qm`
basenames, 301 match `.ts` source basenames; 13 English catalogs have no same-name
`.ts`, including `qtbase_en`. Basename agreement does not reconstruct compiled
translations. The candidate keeps only the 33 Qtbase catalogs, and application
localization has not been established.

SHA1 is used solely to compare upstream inventories; archive trust uses pinned
SHA256. These observations neither rebuild the native modules nor determine
every transitive CVE's applicability. The existing Qtbase `.tag` mismatch,
compiler/build-input gaps, and corresponding-source delivery requirements remain.

## Schannel handshake observations

The separate [loopback probe](../../scripts/probe_qt_tls.py) ran on Qt 6.11.3 and
Python 3.13.17, with Schannel selected. Its successful receipt is
`build/qt-app-validation-20261101/tls-final.json`, observed at
`2026-11-01T19:10:21.539078+00:00`. The executed script's SHA256 was
`aaab48c594d5abdde59199fb7a112d0d83fb453ce71e7729df41955ace9614c1`.

| Case | Actual result |
| --- | --- |
| Probe CA trusted by this socket; `localhost` peer | TLS 1.3 negotiated; expected payload verified; no SSL errors |
| Probe CA untrusted; `localhost` peer | Handshake rejected with `UnableToGetIssuerCertificate` and `SslHandshakeFailedError` |
| Probe CA trusted; incorrect peer name | Handshake rejected with `HostNameMismatch` and `SslHandshakeFailedError` |

The trusted case retained Qt's `UnknownSocketError` accessor value in the raw
receipt; its success is established by encryption and the verified payload.
Both intentionally rejected cases produced server-side `SSLEOFError` after the
client rejected the handshake. The probe did not alter the system trust store.
It checks local certificate and hostname enforcement; it does not establish
public-service compatibility, HTTP/2 patch behavior, loaded-DLL provenance or
frozen-runtime behavior.

## Image runtime and loaded-module checks

A separate standard-user offscreen probe used the final candidate venv with a
minimal child environment and trusted images generated in memory. All 39
installed native members were hashed against the wheel inventory before Qt
imports. Windows process-module enumeration then found 18 loaded Qt/binding/plugin
members, including all nine image-format plugins. Every observed member resolved
inside that venv and matched the expected SHA256. The software OpenGL helper
and Chromium/QML were absent from the loaded module list; no OpenGL context was
created. This observation applies to this image-probe process, not the separate
TLS process or frozen application.

The probe checked every pixel of decoded 16-by-16 images. Solid PNG, BMP, ICO
and TIFF roundtrips were exact; JPEG's maximum channel error was 1 against an
allowed tolerance of 8. A known SVG rectangle rendered with the expected center
color and transparent corner. A patterned lossless WebP roundtrip was also exact.

**The solid lossless WebP case failed.** The candidate encoder produced a
38-byte image, but its reader returned `InvalidDataError`, `Unable to read image
data`, and an invalid preliminary size. A 56-byte patterned WebP decoded
successfully. Matching pinned source shows that `QWebpHandler::ensureScanned`
requires `sizeof(WebPBitstreamFeatures)` bytes before parsing; its five integer
fields and five 32-bit padding fields are consistent with a 40-byte minimum on
this target. That source observation explains the boundary without claiming a
patched plugin or complete diagnosis of all WebP inputs. The compatibility
failure remains unresolved.

An independent decode with the locked **Pillow 13.0.0 / libwebp 1.6.0** runtime
successfully opened the exact same 38-byte fixture, loaded it as 16-by-16 WebP,
and matched all 256 RGBA pixels. Truncated-image loading was explicitly disabled.
The separate `webp-pillow-probe.json` records its script, fixture and decoder
module hashes. This supports a Qt-specific decoder compatibility failure for
this valid tiny fixture rather than an encoder producing malformed data; it
does not establish behavior for other WebP inputs or repair the Qt plugin.

The final targeted comparison reproduced the same rejection in the unchanged
**production Qt 6.11.2** test environment: `InvalidDataError`, `Unable to read
image data`, and preliminary size `[-1, -1]` for the identical fixture. Eight
relevant baseline native files matched the clean production build environment,
and process-module inspection confirmed the expected baseline `qwebp.dll` path
and hash. This classifies this specific case as an existing production decoder
limitation retained by the candidate, not a newly introduced upgrade regression.
The observation is retained in `webp-baseline-probe.json`; it does not clear
the compatibility issue or establish behavior for other images.

The final receipt is
`build/qt-candidate-parity-final-20261101/image-runtime-probe.json`, with status
`completed-with-webp-small-input-failure`. It retains six successful roundtrips,
one failed roundtrip, the SVG observation, and exact loaded-member hashes. The
first two diagnostic failures, generated 38-byte fixture, probe script and
sanitized launcher are also retained and hashed. Inputs were bounded to 65,536
encoded bytes and the reader allocation limit to 1 MiB. This is a small trusted
functional probe, not malformed-input testing or complete decoder coverage.

## Remaining adoption requirements

The candidate still requires coordinated production lock, distribution,
license/SBOM and corresponding-source inventory changes, followed by exact
candidate GPU/Compat frozen builds and recipient rebuild/lifecycle evidence.
Full GUI, remaining image-decoder cases, the small-WebP compatibility finding
and OpenGL behavior still need follow-up.
The unchanged Mesa 11.2.2/LLVM 3.6.2 software helper has its own
[source/security review](../legal/QT_SOFTWARE_OPENGL_SOURCE_REVIEW_2026-11-01.md).
GitHub billing, owner distribution decisions and public delivery remain separate
release gates. This evidence does not authorize a binary release or tag.
