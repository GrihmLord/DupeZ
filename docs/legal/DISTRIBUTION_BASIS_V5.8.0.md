# DupeZ v5.8.0 Distribution Basis

This record identifies the no-purchase distribution route being prepared for
DupeZ v5.8.0. It records upstream terms and engineering delivery controls; it
is not legal advice and does not replace the copyright owner's approval of the
project license.

## Project terms and PyQt

The exact runtime lock installs PyQt6 6.11.0 and PyQt6-WebEngine 6.11.0. Their
wheel metadata identifies both bindings as `GPL-3.0-only`. Riverbank states
that PyQt is dual licensed under GPL v3 and its commercial license, and that a
commercial license is required when the application's terms are incompatible
with GPL:

- https://www.riverbankcomputing.com/software/pyqt/intro/
- https://riverbankcomputing.com/commercial/license-faq

Accordingly, the no-purchase route requires owner-approved GPLv3-compatible
project terms. README currently says `Proprietary. All rights reserved`, while
the shipped About dialog says DupeZ is free and open-source. That contradiction
must be resolved before any distribution build is promoted.

## Qt and Qt WebEngine

The exact PyQt6-Qt6 and PyQt6-WebEngine-Qt6 6.11.0 wheels declare LGPL v3.
Qt's licensing documentation permits the LGPL v3 route when its conditions
are satisfied. Qt WebEngine also incorporates Chromium and third-party code;
both the Qt-specific and Chromium terms apply:

- https://doc.qt.io/qt-6/licensing.html
- https://doc.qt.io/qt-6/qtwebengine-licensing.html

The release payload must provide the corresponding project source, build and
installation information, reverse-engineering/relink rights required by the
applicable licenses, the exact wheel license texts, and the Qt WebEngine
third-party notice route.

## Inno Setup

Inno Setup's website requests that commercial users purchase a support
license. Its controlling `license.txt`, however, grants permission to use the
software for any purpose, including commercial applications, subject to its
four redistribution and attribution conditions. The v5.8.0 no-purchase build
uses that permissive license grant and includes its notice; it does not claim a
purchased commercial entitlement.

- https://github.com/jrsoftware/issrc/blob/main/license.txt
- https://jrsoftware.org/ishelp/topic_purchase.htm

## Delivery controls

The release engineering path must provide, on the exact artifact set:

1. the owner-approved project license;
2. a deterministic consolidated third-party notice/license payload;
3. a source archive made from the exact clean release commit;
4. exact dependency locks and build scripts;
5. installation/rebuild/relink information;
6. SHA-256 checksums, SBOM, vulnerability review, and provenance;
7. the explicit unsigned-publisher warning when Authenticode is unavailable.

The repository is public, but a public working tree alone is not a substitute
for binding the exact source archive and notices to the released binary hashes.
