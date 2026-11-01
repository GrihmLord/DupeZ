# Qt startup controls and pinned payload origins — November 1, 2026

Two additional controls now cover the frozen application's inherited graphics
settings and the isolated candidate's native payload origins. These are bounded
security fixes; production Qt remains 6.11.2 and the Qt 6.11.3 candidate remains
separate from production locks and release approval.

## Frozen graphics settings

`QT_OPENGL=software` alone does not pin the software implementation: Qt's Windows
loader also accepts `QT_OPENGL_DLL`. Bug-list and widget RHI settings can alter
the selected graphics path. The reviewed source confirms these consumers in
`qwindowsglcontext.cpp`, `qwindowsopengltester.cpp` and
`qbackingstorerhisupport.cpp`.
[Qt Windows graphics documentation](https://doc.qt.io/qt-6.11/windows-graphics.html).

The shared Qt-free startup policy removes inherited OpenGL DLL/bug-list,
ANGLE/Quick and widget/RHI selectors case-insensitively, then sets
`QT_OPENGL=software`. It runs in both frozen Windows entry points before
application QtGui initialization and maintenance/GUI dispatch. PyInstaller's
built-in hook can import QtCore earlier; this does not claim to run before every
native import. The child renderer filter uses the same selector classifier.

Ordinary DPI/accessibility variables and the bundle's plugin path are preserved.
Source diagnostics and non-Windows behavior are unchanged. This is a graphics
selector policy, not a complete inherited-environment or plugin-loader audit.

On the verified Python 3.13.17 environment, **96 focused tests passed** across Qt
startup, renderer selection, self integrity, single-instance behavior, privileged
helper startup and maintenance checks. Tests cover mixed-case aliases,
idempotence, preserved settings, execution order, renderer-policy failure and
child environment isolation. The earlier `dbf4d62` GPU/Compat runtime evidence
predates this source patch; it must not be cited as execution evidence for it.

## Fresh clean builds and runtime validation

The new exact checkpoint is `008b1a0c7638bd0f08813145abe3b3e3c5132ebf`.
A fresh isolated checkout produced both engineering executables and an exact
source ZIP using the verified Python 3.13.17/hash-locked build environment.
Source-archive validation, frozen dependency policy and native-origin checks
passed. Each executable has 128 native entries: 100 locked-venv, 24 verified
Python-base and four managed files. Chromium/QML remains absent; Qt TLS is
Schannel-only. These builds retain production Qt 6.11.2.

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Exact source ZIP | 25,002,707 | `d9f791a7c0cb1307fe0802abfb9a4f47790b6ab1f3a90e9be82ce9b71f168650` |
| GPU executable | 69,141,594 | `26f2eac2a2358f450b2dfcc1156158121db7eaa5d5d2f78215b13997b4382222` |
| Compat executable | 69,140,206 | `589e29c53be568a3d518fa40ffd6db707d20f4be51790fe38a2c18c13a5261f7` |

The full production-dependency suite passed **3,544 tests, with ten expected
skips**. The preliminary sandbox run had 22 hard-link/loopback-access failures;
the tests were retained and the same suite passed outside that restriction.
Coverage was not collected again. Ruff and AST checks passed for all 455 tracked
Python files. Source preflight passed with six unresolved licensing warnings.

Both new executables passed runtime-import and TLS maintenance checks. GPU ran
with a standard token; Compat ran through a fresh normal UAC prompt approved by
the owner. Each passed normal and forced-low-resource dashboard lifecycles,
fresh active manual-map validation, no WebEngine helper, clean exit and verified
cleanup. Both actual v4 reports passed the Windows PowerShell 5.1 consumer.
There was no UAC or execution-policy bypass and no packet effect was activated.

The lifecycle validator uses a sanitized child environment. These runs prove
ordinary startup and lifecycle compatibility of the changed binaries; the
adversarial graphics-selector checks are source tests, not an assertion that
the GUI runs exercised inherited malicious DLL values.

The [machine-readable follow-up](../../packaging/license-evidence/qt-startup-native-validation-2026-11-01.json)
binds source/test, build, archive, native, maintenance, lifecycle and consumer
observations. Earlier `dbf4d62` reports remain preserved separately. Neither
checkpoint is a protected-main public release artifact.

## Candidate payload origin verification

Wheel RECORD verification establishes internal consistency, so a substituted
native payload accompanied by a recomputed RECORD can still pass it. The
candidate preparer now additionally compares every retained native file and
translation with bytes read directly from its pinned original input archive.
It does not use the bundler's mutable extracted prefix as the reference.

The comparison covers **39 native files and 33 QM catalogs**. Each output member
must have exactly one origin in the original binding wheel, matching Qt installer
archive or helper archive. Input pins and archive safety checks are enforced.
Native bytes are compared intact, including signatures; no certificate
normalization is used for this check.

The final wheel's size and SHA256 are captured before validation and rechecked
after the complete comparison. Preparation and optional pip installation use
that captured hash. All source input hashes are also rechecked at the end.
This prevents a changed already-compared wheel member from yielding a stale
successful origin receipt.

**81 focused preparer tests passed**, including altered binding, DLL, helper,
plugin and QM bytes with a recomputed RECORD; absent/ambiguous origins; changed
source archives; and a concurrent, equal-length output-wheel mutation with a
valid regenerated RECORD. The concurrent-mutation regression was independently
reproduced during review and passes with the final wheel pin.

Exact preparation and final verifier replay identities are in
[`qt-candidate-origin-review-2026-11-01.json`](../../packaging/license-evidence/qt-candidate-origin-review-2026-11-01.json).
The fresh restricted wheel reproduces the prior 30,238,609-byte candidate:
`5ae71fb933f4cafeaba3eac2d98a35ece588950ea34d3fa5e0252cbc811b29a9`.
Binary origin equality does not prove a native source/compiler rebuild.

## Related results and remaining work

The [translation artifact review](QT_TRANSLATION_SOURCE_REVIEW_2026-11-01-followup.md)
rebuilds all 314 official catalogs byte-for-byte from archived/generated inputs.
The [raster experiment](QT_RASTER_RUNTIME_REVIEW_2026-11-01.md) provides a bounded
path for investigating removal of the old software OpenGL helper. Neither result
adopts a new runtime profile or clears the existing tiny-WebP decoder limitation,
Qt native source-tag/toolchain gaps, historical helper provenance, licensing,
public source delivery, hardware/hotkey validation or hosted CI requirements.
