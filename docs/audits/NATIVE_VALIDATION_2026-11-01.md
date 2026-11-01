# Native validation and remaining release gates — November 1, 2026

Verified source fixes are on the existing PR 84 branch. The clean runtime build
checkpoint is `dbf4d62bee7c9058760d1d94092b992e50a6e0a0`; the later
`b59f982f4eb97912f2db63184c5c570c97b370fb` changes test isolation only.
These are local engineering observations, not release approval.
Machine-readable results are in
[`native-validation-2026-11-01.json`](../../packaging/license-evidence/native-validation-2026-11-01.json).

## Fixed security and test boundaries

The frozen lifecycle validator now requires the exact observed process creation
time before cleanup. Inaccessible identity fails closed; it cannot fall back to
terminating a bare PID or rediscover descendants through a reused root PID.

An early ARP startup failure previously treated its default forwarding-state
flag as proof that it had changed the host. Cleanup could request helper
elevation and disable forwarding despite never having enabled it. Restoration
now belongs only to an actual enable attempt after a successful state query and
journal write. Failed rollback remains pending and blocks restart until retry.
Missing, malformed and ambiguous forwarding observations raise instead of
being treated as disabled.

A read-only query on this Windows host returned multicast and group-fragment
settings, with no unicast `IP Forwarding` label. The old substring parser could
confuse those settings. The hardened parser rejects this output before any
mutation. This native forwarding path remains unavailable until a reviewed
query/update implementation can establish the correct state; functionality
parity is not claimed by this fix.

Preliminary unit runs exposed the real elevation call and were stopped using
their exact process identities. ARP unit tests now fail before unstubbed helper,
subprocess, socket or Npcap access. Idempotence fixtures mock the recovery
journal; separate journal and failure tests retain their coverage. No hardware
effect result is asserted from those interrupted runs.

## Clean production-dependency builds

Both builds used a clean local checkout of the checkpoint, the previously
verified Python 3.13.17 base and the hash-locked build environment. Source archive
validation, both final archive policies and native-origin checks passed.
Each executable has 128 native entries: 100 from the locked venv, 24 from the
verified Python base and four managed native files. Embedded Chromium/QML is
absent and the only Qt TLS backend is Schannel. Production Qt remains 6.11.2.

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Exact-checkpoint source ZIP | 24,863,054 | `03e514c218963e72ba6a4588296812f0ef6667850a6fb6677d52c9ac6bb5c54d` |
| GPU executable | 69,140,289 | `6b4d5af7a0008d4e50de3566a550ef1e593abff00dddc7b0b3164a8c886114a0` |
| Compat executable | 69,138,351 | `f7ab248fcea07bb038977af1e30ff942ba720606fb5b5b71f5895ccbab673338` |

The full production-dependency source suite passed **3,501 tests**, with ten
expected skips: six hardware opt-ins and four unavailable symlink privileges.
Application line coverage was **58.14%**. After test-only isolation changes,
all 139 affected production tests passed. All 452 tracked Python files passed
Ruff and AST parsing. Source preflight passed while preserving all six
unresolved licensing warnings. License payload generation and independent
verification passed for 27 runtime components and 76 notice documents.

GPU import and Schannel-selection maintenance checks passed. Its actual normal
and forced-low-resource dashboard cycles both passed the v4 contract: correct
standard-user split architecture, active Map tab with a fresh approved manual
URL signal, no WebEngine helper, clean exit and verified cleanup. The recorded
evidence passed the canonical Windows PowerShell 5.1 consumer.

**Compat runtime now passes the same bounded checks.** After the earlier
canceled launch, the owner explicitly authorized a fresh normal UAC retry.
The exact-hash helper completed with an administrator token: runtime imports,
Schannel selection, normal and forced-low-resource dashboard cycles all passed.
Both cycles observed `Architecture: inproc | Admin: True`, a fresh active manual
Map view, no WebEngine helper, clean exit and verified cleanup. The actual v4
report passed the canonical Windows PowerShell 5.1 consumer. The record retains
the earlier cancellation separately. No UAC or execution-policy bypass was used;
these safety dry-run checks did not activate packet effects or validate hardware
or disruption hotkey parity.

An earlier diagnostic GPU attempt failed exact-dashboard foregrounding during
concurrent elevation requests; a private-profile wrapper also failed Windows
known-folder lookup. Those observations are preserved separately. The passing
GPU evidence above was produced afterward using canonical validator isolation.

## Separate Qt candidate and source findings

The [candidate review](QT_CANDIDATE_VALIDATION_2026-11-01.md) records a reproduced
Qt 6.11.3 wheel with a verified restricted module/plugin inventory, real local
TLS handshakes, image checks and source/SPDX correlation. Its application test
scope excludes the two modules that import the deliberately absent browser;
production tests cover those modules. The candidate-compatible rerun passed
**3,445 tests, with 18 expected skips**, including eight explicit browser-binding
skips. Candidate and production receipts remain distinct.

The candidate retains an existing tiny-WebP decoder limitation also reproduced
on production Qt 6.11.2. Pillow independently decodes the exact valid fixture.
The [software OpenGL source review](../legal/QT_SOFTWARE_OPENGL_SOURCE_REVIEW_2026-11-01.md)
also confirms the unchanged Mesa 11.2.2/LLVM 3.6.2 helper. Its exact historical
build recipe remains unresolved; LLVM source signature authentication is still
incomplete. New image-format sources correlate with upstream inventories, while
the [translation follow-up](QT_TRANSLATION_SOURCE_REVIEW_2026-11-01-followup.md)
now reproduces all 314 official catalogs byte-for-byte, including all 33 retained
Qtbase catalogs. The missing English TS inputs are generated by the pinned
source recipe. This artifact rebuild uses the official compiler; native
compiler rebuilding and earlier Qtbase tag discrepancies remain open.

The existing 33-archive source bundle and earlier modified-recipient evidence
are retained. This work does not claim a new independent native-source rebuild,
complete corresponding-source delivery, or adoption of the candidate into
production locks/SBOM/notices. Candidate frozen builds, protected-main runtime evidence,
hardware/hotkey parity, billing remediation and owner distribution decisions
remain required. No binary release, tag or merge is authorized by these results.
