# DupeZ v5.8.0 Distribution Basis

The owner has selected GPL-3.0-only open-source distribution with corresponding
source and the explicitly disclosed unsigned/manual-install route. The project
license and selection record are prepared. Contribution rights, six
evidence-backed distribution determinations and complete delivery remain
unfinished; the release policy remains blocked.

## Project terms and PyQt

`LICENSE.txt`, the README and the dated project selection record now describe
the GPL route. Confirm rights to original and outside contributions before
recording the project determination. Third-party components retain their
applicable terms.

The engineering profile now uses PyQt6 6.12.1 and PyQt6-sip 13.13.1. Their
exact source and wheel metadata identify GPL-3.0-only and BSD-2-Clause,
respectively. The source, original wheel, derived/installed package and
generated notice inputs contain matching license text bytes. These are
prepared licensing facts, not a completed source/rebuild or distribution
determination. See the [PyQt6 release](https://pypi.org/project/PyQt6/6.12.1/),
[SIP runtime release](https://pypi.org/project/PyQt6-sip/13.13.1/) and
[pinned licensing review](../../packaging/license-evidence/qt-6121-licensing-review-2026-11-24.json).

The owner has already selected the GPL route. No commercial PyQt purchase or
new proprietary-license selection is needed for preparing that route.
Riverbank offers GPL and commercial alternatives; the actual distribution
must meet the selected terms. See [Riverbank's licensing overview](https://riverbankcomputing.com/software).

The canonical production environment still includes PyQt6-WebEngine; its
licensing must be assessed if its package is distributed through a development
or source channel. It is absent from the new frozen engineering profile.

## Qt and the actual native payload

Canonical production locks select Qt/QtWebEngine 6.11.2. The separate
`frozen-raster-no-qtnetwork` engineering profile uses restricted Qt 6.12.1
upstream binaries and excludes browser/QML, GL/helper and Qt Network payloads.
The profile is not a canonical lock update or distribution approval.

Use the actual frozen inventory when assessing distribution: the verified
GPU/Compat executables retain five Qt bindings, five Qt libraries, fourteen
plugins, the SIP extension and 33 QtBase catalogs. The preparation wheel also
contains PrintSupport and SvgWidgets, which are absent from those frozen
executables. Packaging or delivering that wheel creates a separate artifact
scope. The profile contains 307 collected Qt source notice documents and 379
notice documents overall; counting them does not prove final public delivery.

Pinned retained-source headers provide GPL-3.0-only among their licensing
options. Preserve their other applicable notices and the licenses of bundled
third-party code; do not treat all Qt archive content as one license. See
[Qt's licensing guidance](https://doc.qt.io/qt-6/licensing.html), the
[ImageFormats terms and codec attribution](https://doc.qt.io/qt-6/qtimageformats-index.html#licenses-and-attributions)
and [SVG terms](https://doc.qt.io/qt-6/qtsvg-index.html#licenses-and-attributions).

QtBase and SVG binary SPDX revision declarations match their 6.12.1 source
exports. Their recorded missing infrastructure files and `.tag` checksum
differences remain explicit. ImageFormats' 506 recorded source-SPDX files
match the export exactly or after line-ending normalization, but its binary
SPDX lacks a revision suffix. Translations also lacks that binary revision
declaration and a source-SPDX document. Its 314 catalog rebuilds, including
all 33 retained catalogs, match byte for byte using the official compiler;
this does not rebuild the compiler or native libraries.

The ImageFormats and Translations release tags match the commits in the
official source exports. The tag observations strengthen release-source
identity and do not supply missing binary compiler provenance. Exact native
build inputs and independent native rebuild/replacement remain unfinished.
See the [Qt 6.12.1 adoption audit](../audits/QT_6121_ADOPTION_2026-11-24.md),
[source correspondence record](../../packaging/license-evidence/qt-6121-source-correspondence-2026-11-24.json)
and [catalog rebuild record](../../packaging/license-evidence/qt-6121-translations-2026-11-24.json).

Assess Qt WebEngine/Chromium notices and sources for any separately distributed
payload containing them; do not describe those libraries as present in the new
frozen executable. General upstream licensing guidance is available from
[Qt](https://doc.qt.io/qt-6/licensing.html); exact version/component evidence
must still come from the selected distribution.

## Microsoft runtime files

The three MSVC runtime DLLs in the engineering builds match the signed
Microsoft 14.51.36247
redistributable package exactly. The new profile pins their names, sizes and
hashes and maps them into its engineering SBOM. This establishes package
provenance, not permission to redistribute them.

Microsoft's [redistribution list](https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution)
conditions distribution on a valid Visual Studio license and applicable terms.
The owner must identify the actual edition/eligibility and redistribution
basis; no purchase, entitlement or GPL treatment of these files is inferred
from signatures or an installed runtime. Preserve the applicable notices and
conditions in the exact release channels. See the
[package/license evidence](MSVC_REDIST_PROVENANCE_REVIEW_2026-11-09.md).

## Inno Setup

The [pinned 6.7.1 terms](https://github.com/jrsoftware/issrc/blob/cfdf48923178df4b4f040e038b423aa555a61ffc/license.txt)
permit commercial use under their notice, origin and modification conditions.
The [vendor FAQ](https://jrsoftware.org/inno-setup/purchase)
requests commercial support but states that purchase is not strictly mandatory.
The owner still needs to record the actual usage context and decision to rely
on those terms or a separately evidenced entitlement. An installed compiler
does not establish either a purchased license or an approved decision.

A commercial-support purchase is voluntary under the reviewed terms; it is
not a payment prerequisite that this project should invent. The actual use
context and decision remain unrecorded. This question applies to an Inno-built
installer; it does not replace the notices/source checks for portable files.

## Delivery controls

The exact eventual artifact set must include reviewed project/dependency
terms, deterministic notices, exact application/dependency source and relevant
build inputs, usable replacement/rebuild and applicable installation
information, verified delivery/retention, hashes, SBOM and provenance. Public
repository access and repeatable wheel assembly alone do not satisfy all of
those requirements. The unsigned-publisher disclosure remains required for
the selected manual-install route; protected updater authentication remains
separate.

Complete the six records in `packaging/license-policy.json` only with actual
determinations and pinned evidence. The
[owner runbook](../release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md#owner-action-checklist)
identifies the remaining rights/context inputs and engineering work.

The remaining owner facts are contribution rights, the distributing party's
Visual Studio license/eligibility basis, and actual Inno usage context and
decision. No private keys, license keys or account documents are requested
here. Engineers can continue collecting sources, checking notices and
demonstrating recipient builds while those facts remain unknown. All six
policy decisions remain unresolved; prepared evidence is kept separately
until its corresponding determination is supported.
