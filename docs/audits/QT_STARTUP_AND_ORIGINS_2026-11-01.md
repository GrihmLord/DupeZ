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
