# Native compilation and engineering source delivery — November 24, 2026

Clean code checkpoint `1668606e2856296a757d2442d90fa226bdaae9eb` adds
isolated IUP/Clumsy compilation and an exact-commit source-bundle recipe.
The full suite passes **4,135 tests with ten expected skips**. Both fresh
Qt/PyQt 6.12.1 engineering application builds pass archive/native inspection;
GPU maintenance and dashboard safety dry-runs pass. **Compat runtime remains
pending by owner instruction.** This is engineering evidence, not a public
release approval or a claim of complete corresponding source.

## Native compilation and fixes

The private LLVM-MinGW 20261117 UCRT x86_64 toolchain (LLVM 23.1.6) is
size/hash-pinned, with all 9,069 compiler, header, library and notice files
inventoried. It is extracted into the workspace without a global installation.
The original application-managed Clumsy, IUP and WinDivert files are unchanged.

| Candidate | Verified result | Scope limit |
| --- | --- | --- |
| IUP 3.30 | Two fresh builds compile all 161 selected C files and produce byte-identical DLL/import-library outputs. All 728 exported names and ordinals match the original DLL; all 32 Clumsy IUP imports are covered. | Alternative-toolchain compilation, not reconstruction of the historical MSVC binary. |
| Upstream Clumsy | Two fresh builds compile all 15 C files from the pinned upstream commit and produce byte-identical executables. All 32 IUP and seven WinDivert imports are covered and match the original import tables. | Compile/data inspection only; the executable was not run and local vendored functional changes are outside this proof. |
| IUP inert harness | Exact-origin/version load, hidden controls, attribute round trip, one harmless callback and all four RGBA pixels of a private 2-by-2 image pass; IUP close and cleanup calls are exercised. | Limited API/image exercise; no full Clumsy integration, packet engine, driver or Compat execution. |

The first IUP compilation exposed an incompatible `BYTE**` argument to the
`void**` output of `CreateDIBSection`. The retained patch uses a typed `void*`
temporary, then assigns it to the byte pointer. Its exact preimage/postimage
is pinned; no other upstream source file changes. The failed attempt remains
in the record.

Clumsy uses the complete pinned GENie source list. Its old Zig recipe omits
files and duplicates another source entry. The unchanged upstream C requires
the documented `-fcommon` configuration for a tentative global definition in
`common.h`. The recipe selects LLD explicitly and reproduces the private
compiler runtime configuration while disabling ambient configuration files.
Early missing-header, linker-wrapper and duplicate-definition failures remain
recorded. Exact driver bytes for the first two preliminary attempts were not
retained; their logs and receipt assertions are identified as limited evidence.

The new process guard creates children suspended, assigns a no-breakaway
Windows Job before their first instruction and inherits only explicit log
handles. Bounded execution terminates the owned process tree and waits for
retained process handles to signal before releasing input locks. Tests caught
and fixed a race where a zero active-job count preceded process completion.
Source/tool inputs remain locked and are rehashed before and after use.
The source wrapper also rejects Windows case aliases, binds recipes and the
manifest to exact Git blobs, and retains verified hashes across lock release.

The final full suite includes 118 more passing tests than the earlier Qt
adoption checkpoint. Focused native input/process/Clumsy tests pass, including
ownership-before-resume failures, bounded cleanup and source integrity cases.

Native evidence:

- [IUP compilation and inert test](../../packaging/license-evidence/iup-native-compilation-2026-11-24.json)
- [Clumsy compilation and import comparison](../../packaging/license-evidence/clumsy-native-compilation-2026-11-24.json)
- [Exact patch](../../packaging/native-patches/iup-3.30-win32-dib-pointer.patch)

## Application rebuild and runtime evidence

The fresh checkout uses the explicit `frozen-raster-no-qtnetwork` profile,
Qt/PyQt 6.12.1 and SIP 13.13.1. Canonical production locks remain unchanged.
Ruff and AST checks pass all **486 tracked Python files**. The complete
JUnit result is 4,145 cases: 4,135 passed, ten expected skips, zero failures
and zero errors.

Both frozen artifacts have **114 verified native entries**: 83 from the locked
environment, 24 from the CPython base, four managed native files and three
private Microsoft runtime files. No System32-origin file is accepted.
Independent review re-extracted all native entries from both executables and
matched their recorded bytes and origins.

GPU import maintenance and the local Python TLS-backend check pass. The TLS
maintenance check does not perform a network connection. Normal and forced
low-resource dashboard safety dry-runs exit cleanly. The actual Windows
PowerShell 5.1 evidence consumer accepts the exact artifact hash and commit.
Compat was inspected as data only; no Compat report, launch or UAC attempt is
claimed. No Clumsy executable, WinDivert driver or packet effect was activated.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Exact application source ZIP | 25,467,638 | `a6570dde831fefe60cceb428dc3429dda8b5896b4a64f918b782b0e32c05dec5` |
| GPU executable | 57,273,211 | `0164d93bdfdd8bf188de81911510275e56eb42dcbce0074139b3db48e91c102a` |
| Compat executable | 57,275,131 | `2962628520d3ab21a029092ad04924d5b13ad8a2154e0f2ad1368da996506942` |

The [application verification record](../../packaging/license-evidence/native-source-builds-2026-11-24.json)
binds source, commands, logs, inventories, artifacts and reports. Its false
complete-native-rebuild flag is retained: the separately recorded IUP/Clumsy
experiments do not prove complete historical native reconstruction.

## Engineering source bundle

The [engineering manifest](../../packaging/engineering-source-inputs.json)
accounts for **46 components**, with **45 original source archives** totaling
227,653,716 bytes. The bundle contains those archives, the exact application
source ZIP, effective notices, profile/component/native mappings, recipes and
dated supporting observations. The recipe and manifest bytes match checkpoint
`1668606`; newer observations are explicitly separate supporting evidence.
Both GPU and Compat mappings account for all 114 native entries.

Two fresh collections and separate-process verifications pass. Both ZIPs and
their receipts are byte-identical. The ZIP has **97 payload files** and is
**256,667,781 bytes**, SHA-256
`dfb8b18dfd060db38685be0386d3a063b90bc73367d5ffe64e9de2639a00bd8e`.
Each receipt is **25,652 bytes**, SHA-256
`97b3b841cfbe0c519e554e8eea644f2948bee8f5c4c763e838258ca81a379628`.
The local copies are under `build/engineering-source-20261124/final-a2` and
`final-b`. The initial sandboxed publication failed with Windows access denied
at the no-overwrite hard-link operation; the identical reviewed recipe passed
in fresh workspace-only outputs without a code change.

See the [machine delivery record](../../packaging/license-evidence/engineering-source-delivery-2026-11-24.json)
for the independently checked receipt hashes and the
[recipient recipe](../legal/ENGINEERING_SOURCE_REBUILD_2026-11-24.md) for create,
verify and native compilation commands. A recipient must obtain the expected
receipt digest through the published evidence channel before trusting a bundle.

These are fresh outputs on the same machine, not an independent recipient's
machine. The bundle is locally verified and has not been published as a release
asset. Microsoft runtime source remains uncollected. Source mapping does not
establish native binary equivalence, and the bundle does not include every
compiler/import-library binary input. All completeness, distribution approval,
public delivery and release flags remain false.

## Licensing and remaining release work

The [licensing review](../../packaging/license-evidence/qt-6121-licensing-review-2026-11-24.json)
verifies the prepared PyQt/SIP terms, 307 Qt source notice documents and pinned
Inno terms. GPL-3.0-only with corresponding source and the disclosed unsigned
manual-install route remain owner-selected. All six decisions in
`packaging/license-policy.json` remain unresolved; no rights, entitlement or
distribution approval has been invented.

The remaining work is:

- Rebuild and validate the remaining native components, including retained Qt
  and transitive native code, and complete the source/replacement mappings.
  The private alternative compiler does not supply the missing historical
  MSVC toolchain. ImageFormats/Translations binary revision metadata and the
  Qt source-SPDX discrepancies remain recorded gaps.
- Complete actual public source/notices/relink delivery and retention, plus
  applicable installation information. The original managed native files
  require their own proven replacement and compatibility route.
- Record contribution rights, the actual Visual Studio redistribution basis
  and Inno use context, then complete the evidence-backed determinations.
  See the [owner-action checklist](../release-notes/BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md#owner-action-checklist).
- Complete Compat runtime testing when requested, exact-build hardware/hotkey
  validation, retained-native security review and the unresolved tiny-WebP
  decoder limitation. No broad security-clearance claim is made.
- Resolve the GitHub account billing restriction and obtain passing current
  hosted checks. Before this push, all 14 checks on `03c8677` were blocked
  before execution. Consult [PR 84](https://github.com/GrihmLord/DupeZ/pull/84)
  for diagnostics on the new head; local validation does not replace hosted
  checks or protected release gates.

Independent agent reviews checked the native records, build inputs and
application evidence. These are engineering cross-checks, not an independent
maintainer review, legal approval or a second-machine reproducibility result.
