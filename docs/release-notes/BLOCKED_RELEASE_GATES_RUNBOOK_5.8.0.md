# Blocked Release Gates Runbook (v5.8.0)

This runbook completes the protected v5.8.0 artifact gates in strict order.
Source tests and a clean merge are prerequisites, not substitutes for testing
the exact frozen files that will be published.

## Preconditions

- GitHub `main` requires a pull request, resolution of review conversations,
  and all 14 up-to-date exact-head checks; force push, deletion, direct update,
  and bypass are disabled.
- The `production-release` environment permits deployments only from `main`.
  DupeZ currently has one write-capable maintainer, so no independent-review
  claim is made; mandatory automated checks compensate until a second trusted
  maintainer can be required for review.
- After API-verifying those controls, repository variable
  `DUPEZ_RELEASE_GOVERNANCE_READY` has the exact value
  `protected-main-solo-maintainer-environment`; leave it unset while either
  control is absent.
- The 2026-09-04 read-only audit verified those settings and is preserved at
  `assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-09-04.json`. Re-verify
  live settings before release because repository policy can change.
- Branch: `main` at the exact-head-validated v5.8.0 commit.
- Working tree: clean (`git status --porcelain` is empty).
- `packaging/license-policy.json` records owner evidence for every decision,
  and the root `LICENSE.txt` is compatible with the exact PyQt binding terms.
- Windows PowerShell 5.1 and Administrator access for protected phases.
- Inno Setup 6, current Microsoft Defender, and the expected build tools.
- Updater private key matching fingerprint `5555f0e8c31a40ed`.
- Authenticode inputs, unless the explicitly disclosed unsigned path is used.
- Passing GitHub Actions `Hardware Smoketest` evidence for this exact commit,
  exact canonical hardware suite, and measured post-cleanup process count, downloaded from
  the prepared private-target runner without target identifiers.
- GitHub authentication through `GITHUB_TOKEN` or `GH_TOKEN`.

## Owner-action checklist (2026-10-25)

The owner has selected the explicitly disclosed unsigned/manual-install route
and approved GPL-3.0-only open-source distribution with corresponding source.
Those choices do not establish contribution rights, complete dependency-source
delivery, or passing release validation. The six licensing decisions remain
unresolved in `packaging/license-policy.json`; do not publish or mark them all
approved merely because `LICENSE.txt` now exists.

### 1. Resolve the GitHub Actions billing lock

The October 25 checks for prior pushed commit
`6fa81f48b1c96c949abe27b4822805914d128e78` all reported this annotation:

> The job was not started because your account is locked due to a billing issue.

All 14 checks were affected. The Python 3.12/3.13, Ruff, and AST-lint jobs had
no assigned runner and zero executed steps. See the
[affected Actions run](https://github.com/GrihmLord/DupeZ/actions/runs/40178258754).
This is an account-level start failure, not a failing test assertion. The owner
has not yet confirmed that the lock is resolved. Recheck the newest candidate
head after remediation; this dated observation is not a substitute for live
check results.

The October 25 local build checkpoint `bca1e44` additionally passes both frozen
offline archive checks and GPU maintenance/manual-map lifecycle checks. The
Compat runtime attempt was canceled at normal Windows UAC before it started.
Approve normal UAC when ready to complete that prepared test; do not substitute
offline archive success for administrator runtime evidence. See the
[exact-build record](../audits/NATIVE_CONTAINMENT_2026-10-25.md).

1. Sign into the GitHub account that owns `GrihmLord/DupeZ`. Open
   [Billing & licensing](https://github.com/settings/billing), then
   **Payment information**. For an organization-owned repository, use that
   organization's Settings > Billing & Licensing instead.
2. Review the actual account message and payment history. If an existing
   payment or authorization was declined, resolve it directly with GitHub or
   the payment provider. Updating payment information can trigger a charge for
   an existing paid product; review that commitment yourself. No payment,
   subscription, card update, or purchase is authorized by this runbook.
3. If there is no active subscription, balance, or payment issue to resolve,
   use [GitHub Support](https://support.github.com/contact) to request a billing
   lock review. A failed authorization hold can block Actions even on a Free
   account with no visible balance. Successful payment processing can take up
   to 24 hours. Follow
   [GitHub's account-unlock instructions](https://docs.github.com/en/billing/how-tos/troubleshooting/locked-account).
4. Check **Budgets and alerts** only if GitHub identifies an exhausted budget
   as a separate block. Do not assume this annotation means a budget must be
   increased, a paid plan purchased, or a spending cap disabled. Any applicable
   hard-stop budget can block usage; the owner must explicitly choose any
   spending change. See
   [GitHub's budget controls](https://docs.github.com/en/billing/how-tos/set-up-budgets).
5. Tell the release operator when GitHub confirms resolution. Rerun and obtain
   all required checks on the newest exact PR head. Preserve branch/environment
   protections; do not replace hosted evidence with local results or a bypass.

Do not paste payment details, invoices containing personal information, or
authentication secrets into the repository or this release record. No amount
due, required purchase, or free remediation outcome is assumed.

Suggested Support request (send privately, adding only the account information
GitHub requests):

> Please review the billing lock on the account owning GrihmLord/DupeZ. Actions
> checks on PR 84 fail before a runner or any steps start, with the annotation
> "The job was not started because your account is locked due to a billing issue."
> Example: https://github.com/GrihmLord/DupeZ/actions/runs/40072035110 . Please
> identify the payment/authorization issue or review and clear an incorrect lock,
> and tell me the available remediation. I have not changed spending limits to
> bypass it.

### 2. Confirm rights for the selected project license

`LICENSE.txt` contains the unchanged GNU GPLv3 text. The version-3-only choice
is recorded separately in
`packaging/license-evidence/project-distribution-terms-2026-10-24.txt`;
the sample "or any later version" notice in the GNU appendix does not change
that selection.

The remaining owner answer is whether the owner holds the original DupeZ
contribution rights or has permission to distribute those contributions under
GPL-3.0-only. Identify any outside, employer-owned, contractor-owned, copied,
or other third-party contributions whose permission is not already established.
Resolve exceptions before approving the project determination; do not invent
copyright ownership or erase existing notices. Third-party components keep
their own applicable terms.

After that answer, the release operator can record the actual confirmation and
date, hash the completed decision record and `LICENSE.txt`, and update only
the supported project decision. The current record deliberately does not
certify ownership or corresponding-source completion.

The pinned [PyQt6 6.11.0](https://pypi.org/project/PyQt6/6.11.0/) and
[PyQt6-WebEngine 6.11.0](https://pypi.org/project/PyQt6-WebEngine/6.11.0/)
PyPI packages identify GPL-3.0-only terms. A commercial PyQt purchase is not
required merely because software is sold when the applicable GPL obligations
are met. Do not silently substitute a proprietary distribution basis or assume
a commercial entitlement. See
[Riverbank's licensing FAQ](https://www.riverbankcomputing.com/commercial/license-faq).

### 3. State the Inno Setup usage context and decision

Record whether this use is commercial under the vendor's stated definition:
a for-profit organization, or an individual using Inno for for-profit work,
with annual revenue exceeding USD 5,000 or equivalent. Open-source/freeware
donations count toward that threshold. Do not infer the answer from the
repository being public or the application being free.

The [exact Inno Setup 6.7.1 license](https://github.com/jrsoftware/issrc/blob/is-6_7_1/license.txt)
permits commercial use subject to its notice and other conditions. The
[current purchase FAQ](https://jrsoftware.org/isorder.php) requests support
from commercial users but says purchase is not strictly required. The owner
may approve use under that existing permissive grant, or identify a separate
entitlement if they choose one. Do not claim an installed compiler proves a
purchased license, and do not require a purchase that the pinned terms do not
require. Record the owner's actual context and decision, not an invented
noncommercial classification.

### 4. Complete the six evidence-backed distribution decisions

The release operator can prepare the files, inventory, hashes, and validation;
the owner supplies the rights/usage answers and approves the actual
determinations. Approval must describe verified delivery, not promise that
unfinished engineering is already complete.

| Decision ID | Owner determination needed | Concrete evidence to prepare and verify |
| --- | --- | --- |
| `project-distribution-terms` | GPL-3.0-only selection plus contribution rights | `LICENSE.txt` and completed dated project decision record |
| `pyqt-distribution-basis` | GPL basis for both exact PyQt binding packages | Exact wheel metadata/license texts, source mapping, and dated determination |
| `qt-qtwebengine-distribution-basis` | Open-source distribution basis for the actual bundled Qt/WebEngine/Chromium components | Exact component inventory, applicable license texts, source/patch/build-input mapping, and determination |
| `third-party-notices-delivery` | Approval of demonstrated notice delivery in every channel | Validated `LICENSE.txt`, `THIRD_PARTY_NOTICES.txt`, and `license-payload.json`; exact portable and installer payload checks/hashes |
| `source-and-relink-delivery` | Approval of demonstrated source/replacement route and retained availability | Exact-commit source archive, exact dependency sources and patches, usable build/replacement instructions, recipient rebuild evidence, and delivery record |
| `inno-setup-commercial-use-basis` | Actual commercial context and use of the permissive grant or a separately evidenced entitlement | Pinned 6.7.1 terms, current vendor guidance, and dated owner decision; purchase evidence only if that route is chosen |

The policy schema is `dupez.license-policy.v1`. Each decision has only
`id`, `state`, `determination`, `evidence`, and `required_owner_action`.

- `unresolved` requires a null determination and an empty evidence list.
- `evidence-recorded` requires a nonempty owner determination and evidence.
- Each evidence object contains exactly `kind`, `reference`, and `sha256`.
  `sha256` is the lowercase 64-character SHA-256 of the referenced evidence.
- Prefer `kind: repository-file` with a safe repository-relative POSIX path
  such as `packaging/license-evidence/project-distribution-terms-2026-10-24.txt`.
  The preflight checks that the regular, non-reparse file exists and its hash
  matches. Rehash after any approved content change.
- `kind: external-record` is supported for records that should not be committed.
  Its reference and hash syntax are checked, but the preflight does not fetch
  or authenticate the external content. Independently review it; do not claim
  that schema validation establishes entitlement or legal compliance.
- Update `reviewed_on` to the actual review date in `YYYY-MM-DD` format.
  `release_state` stays `blocked` while any decision is unresolved; only when
  all six have evidence does it become `evidence-recorded`.

Set `DUPEZ_BOOTSTRAP_PYTHON` to the absolute path of the verified canonical
64-bit release interpreter, then validate completed records from the repository
root:

```powershell
& $env:DUPEZ_BOOTSTRAP_PYTHON -I scripts/release_preflight.py --license-distribution
```

An `evidence-recorded` state means a determination and pinned evidence exist;
it is not a legal opinion or permission to skip the remaining release gates.

### 5. Finish corresponding-source and recipient-rebuild engineering

The current `docs/legal/SOURCE_AND_RELINK_V5.8.0.md` and planned source ZIP
are a starting point, not proof of complete corresponding-source delivery.
The engineering work still must:

- Bind the application source, build scripts, dependency versions, exact
  dependency source archives, patches, and relevant build inputs to the
  shipped binaries. A generic upstream link or moving branch is not an exact
  source mapping. Verify and retain availability of the selected source route.
- Include applicable Qt and Chromium notices and source obligations, even
  where the library is unmodified. Review the actual shipped components using
  [Qt's GPL/LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations)
  and the [Qt 6.11 WebEngine licensing map](https://doc.qt.io/qt-6.11/qtwebengine-licensing.html).
- Document and test how a recipient changes the application or a covered
  library, rebuilds/replaces the frozen copy, and runs that modified copy.
  Temporary DLL extraction by a onefile executable is not, by itself, proof of
  a usable replacement/relink route. Preserve applicable reverse-engineering
  and installation rights; assess which installation-information duties apply.
- Validate the independent, keyless recipient recipe now documented in
  `docs/legal/SOURCE_AND_RELINK_V5.8.0.md`. It invokes the packaging specs in a
  separate clone rather than the protected finalizer, which requires the
  production Ed25519 updater key even for unsigned releases. Do not distribute
  that secret or weaken updater verification. The recipe is not yet tested;
  a recipient rebuild is not an official update or release-approved artifact.
- Keep official DupeZ release publication on this runbook's protected finalizer
  and exact-byte validation sequence. Do not add a bypass flag to solve
  recipient rebuilding. This internal release process does not restrict
  downstream rights granted by the applicable licenses.

The independent recipient-build design requires review and verification before
the source/relink decision can claim completion. Owner approval of GPL source
publication does not turn this outstanding work into a completed deliverable.

## Canonical launcher

Start with the read-only status view:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Version 5.8.0
```

Progress is version-bound in `dist/blocked-release-gates-progress.json`. The
launcher also binds progress to the exact commit, release mode, and validation
policy. It ignores stale progress in read-only status, waits for protected
elevated phases, and refuses to perform GPU validation from an Administrator
shell. Use the explicit named phases below for the auditable release sequence.
`-Phase auto` may select the next non-publication phase, but it always stops
before publish; publication requires explicit `-Phase admin-stage-publish`.

Progress saves now flush a private sibling file before replacing the checkpoint.
An unsuccessful replacement leaves the previous checkpoint intact. Phase work
and reset take exclusive OS-handle ownership of
`dist/blocked-release-gates-progress.json.lock`; competing launchers fail without
starting a phase. The lock file stays on disk after normal completion: its
existence is not evidence that a release is still running. Do not delete it to
try to bypass a running launcher. Status remains read-only and unlocked.

If a launcher crashes after starting a phase, inspect its child processes and
external effects before retrying. Checkpoint persistence is not a transaction
covering builds, hardware tests, uploads, or publication. Automatic selection
is repeated after elevation, and selection is checked again under the lock.

Useful commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase status -Version 5.8.0
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase reset -Version 5.8.0
```

## Exact sequence

### A. Administrator: finalize exact artifacts

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-finalize -Version 5.8.0
```

For the explicitly disclosed unsigned public route, append `-AllowUnsigned`.
The updater manifest still requires the protected Ed25519 key.
Keep that switch on every subsequent phase, including GPU validation,
Compat/manual, draft, and publish. Launcher progress is release-mode-bound, and
each phase fails closed if the switch is omitted.

### B. Standard desktop: GPU runtime validation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase gpu-validate -Version 5.8.0
```

For the unsigned route, append `-AllowUnsigned` here and on every later phase.

### C. Administrator: Compat and manual validation

Before this phase, place the matching workflow artifact at
`dist/hardware-smoketest-evidence.json`. The recorder revalidates its commit,
passing/non-skipped test count, zero owned-process remainder, and every source
native size/SHA-256 against `packaging/binary-provenance.json`. Hardware runs
exercise source at the exact commit; frozen GPU/Compat hashes remain bound by
their separate runtime evidence. Draft staging then authenticates that local
copy against the successful exact-commit GitHub Actions run, exact artifact ID,
GitHub archive digest, and downloaded evidence bytes.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-compat -Version 5.8.0 -Operator "YOUR_NAME"
```

For the explicitly disclosed unsigned public route, append `-AllowUnsigned`
so the manual evidence is bound to the attested unsigned distribution mode.

The manual recorder requires explicit observation of every listed behavior on
the exact GPU, Compat, and installer bytes. Do not record an unobserved pass.

### D. Administrator: create and verify the draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-draft -Version 5.8.0
```

Unsigned route:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-draft -Version 5.8.0 -AllowUnsigned
```

### E. Administrator: publish the verified draft

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-publish -Version 5.8.0
```

Unsigned route:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release.ps1 -Phase admin-stage-publish -Version 5.8.0 -AllowUnsigned
```

## Required private evidence and public artifacts

- `dist/release-attestation.json`
- `dist/frozen-runtime-evidence-gpu.json`
- `dist/frozen-runtime-evidence-compat.json`
- `dist/hardware-smoketest-evidence.json` (private input; summarized in the
  public validation attestation)
- `dist/manual-release-validation.json`
- `dist/release-validation-attestation.json`
- GPU and Compat executables, versioned and stable installers
- updater manifest/signature, SHA-256 list, SBOM, lock-bound vulnerability
  review generated within the preceding 24 hours, provenance, and Defender
  report
- project `LICENSE.txt`, `SOURCE_AND_RELINK.txt`,
  `THIRD_PARTY_NOTICES.txt`, `license-payload.json`, and the exact-commit
  `DupeZ-v5.8.0-source.zip`

Frozen-runtime JSON is private, unsigned operator evidence with a 24-hour
freshness limit and per-invocation session binding. It is not cryptographic
provenance and must never be substituted for the signed release attestation.

Publication is permitted only after the draft is downloaded and every staged
asset hash matches the locally validated artifact.
