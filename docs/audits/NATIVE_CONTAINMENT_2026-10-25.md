# Browser-free build and runtime observations — 2026-10-25

The final build checkpoint is **`bca1e44b161984e90c8f9ce1430b7d7a62e40f09`**.
Both clean archives pass offline verification; GPU maintenance and dashboard
lifecycle checks pass. **Compat runtime was not executed:** Windows canceled
the normal UAC request before the helper started. These are local engineering
observations, not release, licensing or complete corresponding-source approval.

Exact hashes and results are retained in
[native-containment-2026-10-25.json](../../packaging/license-evidence/native-containment-2026-10-25.json).

## Changes and failures resolved

Both frozen variants now omit WebEngine/Chromium, WebChannel, QML/Quick,
browser helper modules and browser resources. Build Analysis and the final
outer/PYZ archives reject their reintroduction. The first real build caught
two browser designer source files collected by PyInstaller's `uic` hook;
only those two known files are explicitly omitted before the strict check.
That failed build produced no executable and was never launched.

Maintenance checks require QtNetwork instead of the omitted browser bindings.
The manual HTTPS map URL remains selectable and copyable. Dynamic device,
model and recommendation text is escaped where formatted HTML is intentional;
status labels and configuration editors use plain text where formatting is
unnecessary. This reduces rich-text parsing exposure without claiming that
every Qt vulnerability has been patched.

Lifecycle evidence advances to **v4**. A fresh post-Ctrl+2 signal is emitted
only after the active Map tab validates its mounted plain-text catalogue URL
and confirms no retained browser or incomplete cleanup. The validator and
shared PowerShell consumer reject old v3 evidence, unexpected renderer activity,
missing application processes and ordinary unavailable/error placeholders.
Source, hash, architecture, freshness, session and shutdown checks remain.

## Fresh build and test results

A new venv installed the unchanged runtime/build locks with required hashes
and binary-only inputs. `pip check` passed. Builds used the exact source ZIP,
new Analysis/output directories, verified PSF Python 3.13.17, PyInstaller
6.22.2, and process-local removal of signing/release overrides. The canonical
`dist` directory was not changed.

| Observation | GPU | Compat |
| --- | --- | --- |
| Executable bytes | 69,139,277 | 69,138,230 |
| Final native entries | 128 | 128 |
| Native origins and frozen dependency policy | Passed | Passed |
| Runtime imports / Schannel-only probe | Passed, standard token | Not run; UAC canceled |
| Normal and low-resource dashboard cycles | Both passed | Not run; UAC canceled |

The previous clean builds contained 259 native entries and were about 229 MB.
The new native inventories match across variants: 100 entries from the locked
venv, 24 from verified Python and four pinned managed binaries. No browser/QML
payload remains in either final archive. This is an inventory comparison, not
a count of resolved vulnerabilities.

GPU lifecycle checks ran from a separate clean local Git checkout of the exact
built commit. Both profiles reported `Architecture: split | Admin: False`,
activated the validated manual map URL, observed no WebEngine child and exited
cleanly with no crash files. The application's production safety dry-run mode
was required before exercising the Map and quit shortcuts. No packet-engine or
disruption-hotkey effect was tested.

The stable checkpoint suite passed **3,367 tests**, with **10 expected skips**,
**58.40% application line coverage**, in **198.47 seconds**. Six skips require
opt-in hardware and four require symlink privileges. A partial logging rollover
diagnostic appeared on stderr; pytest reported no failed assertions or errors.
The preceding in-progress run's outdated renderer assertion was corrected;
its failure is retained separately from this passing report.

The exact-commit source ZIP gate passed. Notices were regenerated and verified:
**27 runtime components and 76 notice documents**. No licensing decisions were
changed. The source ZIP is 24,793,147 bytes, SHA-256
`41ecb425d4538f1d1e405f4134dba97209738010cb2b4694f3eea23d37c43e70`.

## Completing the pending Compat check

Windows returned “The operation was canceled by the user” for the normal
`Start-Process -Verb RunAs` launch. No Compat process handle, maintenance report
or lifecycle log was created. No elevation or execution-policy bypass was used
and no second prompt was attempted.

When the operator is ready to approve normal UAC, the prepared local helper is
`build/recipient-evidence-20261025/checkpoint-bca1e44/run-compat-validation.ps1`.
It first checks the administrator token, then verifies the pinned Compat bytes
with `scripts/verify_frozen_maintenance.py`, and runs the v4 safety dry-run
lifecycle validator in the clean exact-commit checkout. It uses fresh report
paths and stops on failure. This local helper is not distributed release code.
Do not label Compat tested merely because its archive passed offline checks.

## Separate source and patched-Qt progress

[Native mapping](../legal/NATIVE_SOURCE_MAPPING_2026-10-25.md) matches all four
managed native files to official release packages. IUP source is now retained,
bringing the verified bundle to **33 archives**. Its source archive was replaced
in 2023 after the binary release; matching headers do not prove the exact
historical source or an independent native rebuild.

[Qt candidate review](QT_NATIVE_REVIEW_2026-10-25.md) documents an official
installer-based Qt 6.11.3 candidate, source/SPDX comparisons, runtime widget/SVG/
Schannel checks and a hardened recipient preparer. **51 preparer tests passed**;
independent preparation reproduced all **933 wheel member payloads**, not an
identical ZIP hash. That candidate is separate from these Qt 6.11.2 builds.

Production integration still needs a coordinated lock/license/source inventory,
plugin parity, full application/frozen validation and actual TLS connection
tests. The retained software OpenGL helper also requires source/security review.
Native rebuild/replacement, public source delivery/retention, owner decisions,
hardware evidence and billing-blocked hosted CI remain unresolved. No binary,
release tag or public release is authorized by this record.
