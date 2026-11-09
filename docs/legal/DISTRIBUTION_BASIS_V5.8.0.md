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

The PyQt6 6.11.0 binding metadata identifies GPL-3.0-only. The new engineering
profile uses a derived PyQt6 distribution with a restricted Qt 6.11.3 payload;
its source and modification mapping must match those actual bytes. Riverbank
bases the need for a commercial license on compatibility with the GPL, not
merely on whether the application is sold. A commercial entitlement is not
assumed. See [Riverbank's FAQ](https://www.riverbankcomputing.com/commercial/license-faq).

The canonical production environment still includes PyQt6-WebEngine; its
licensing must be assessed if its package is distributed through a development
or source channel. It is absent from the new frozen engineering profile.

## Qt and the actual native payload

Canonical production locks select Qt/QtWebEngine 6.11.2. The separate
`frozen-raster-no-qtnetwork` engineering profile uses restricted Qt 6.11.3
upstream binaries and excludes browser/QML, GL/helper and Qt Network payloads.
The profile is not a canonical lock update or distribution approval.

Use the actual retained component inventory, licenses and pinned source
documents to determine obligations. The 304 collected Qt source documents and
generated notice payload are engineering inputs, not proof of every required
notice or full public corresponding-source delivery. QtBase/Core revision
metadata, exact native build inputs and independent native rebuild/replacement
remain unresolved. See the [new profile audit](../audits/QT_NETWORK_EXCLUSION_2026-11-09.md)
and [source metadata review](../audits/QT_SOURCE_METADATA_REVIEW_2026-11-09.md).

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

The [pinned 6.7.1 terms](https://github.com/jrsoftware/issrc/blob/is-6_7_1/license.txt)
permit commercial use under their conditions. The [vendor FAQ](https://jrsoftware.org/isorder.php)
requests commercial support but states that purchase is not strictly mandatory.
The owner still needs to record the actual usage context and decision to rely
on those terms or a separately evidenced entitlement. An installed compiler
does not establish either a purchased license or an approved decision.

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
