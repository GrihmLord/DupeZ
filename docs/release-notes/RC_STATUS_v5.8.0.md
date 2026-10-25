# DupeZ v5.8.0 Release-Candidate Status

Status date: 2026-08-31

> Historical snapshot, not current launch authorization. The governance claims
> below were superseded by the 2026-09-04 audit and rechecked on 2026-09-05.
> Use [the current launch plan](LAUNCH_PLAN_5.8.0.md) for present blockers and
> next steps. Historical validation results apply only to their original bytes.

## Current disposition

- Source/engineering candidate: **PUSHED with external and owner gates pending**.
  Exact head `eeffd65631f12e4cbb87f14373c514db75adffed` is under review in
  draft pull request <https://github.com/GrihmLord/DupeZ/pull/84>.
- Private unsigned frozen snapshot: **validated engineering evidence only**.
- Public Windows release candidate: **BLOCKED**.
- Published release: **not authorized and not attempted**.

No canonical `dist` file was replaced, no tag or GitHub Release draft was
created, and no purchase or account registration was performed. The source
candidate branch and draft pull request were pushed only after the complete
local gate and repository commit hooks passed.

## Verified locally

- Full CPython 3.13.14 x64 suite: 2,285 passed, 10 expected
  hardware/host-capability skips; 54.20% application coverage against the 40%
  gate.
- Focused legal/release pipeline suite after the final legal-reference edit:
  130 passed.
- Ruff, compile-all, `pip check`, four exact requirement-lock contracts,
  PowerShell parsing, workflow YAML parsing, and `git diff --check`: passed.
- Runtime dependency review: 27 exact locked packages, zero active advisories
  in both `pip-audit` and the canonical package/version review.
- Bandit: zero medium/high findings. Its 227 low findings remain visible rather
  than suppressed; 159 are broad exception-cleanup heuristics and the balance
  is primarily subprocess/import, pseudorandom, assertion, and token-name
  heuristics.
- Production AST audit: no concrete function body is implemented only as
  `pass`, `...`, or `NotImplementedError`. The five ellipsis bodies are three
  `Protocol` methods and two abstract methods. Remaining non-exception `pass`
  statements implement explicit validation-success, lock-drain, or
  user-adjustment branches; the one empty class is an exception type.
- Secret/path review: no high-confidence source secret and no personal
  workspace path was found in the reviewed release changes or generated legal
  payload. The seven private frozen artifacts/evidence files have zero
  forbidden-path findings.
- Deterministic legal-payload smoke: all 27 exact runtime components and 76
  notice documents collected and hash-verified. This used an expressly
  non-release placeholder project license because the owner license is still
  unresolved; it did not touch canonical `dist`.
- Private GPU frozen lifecycle: normal and forced-low-resource profiles both
  reached the dashboard with WebEngine ready, used production safety dry-run,
  and exited cleanly. The snapshot is deliberately labelled dirty-validation
  and `release_candidate: false`.

Primary local evidence:

- `build/release-validation-private-20260831-final5/validation-summary.json`
- `build/release-validation-private-20260831-final5/artifact-audit.json`
- `build/release-validation-private-20260831-final5/source/dist/frozen-runtime-evidence-gpu.dirty-validation.json`
- `build/security-audit-rc-20260831/bandit.json`
- `build/security-audit-rc-20260831/pip-audit.json`
- `build/security-audit-rc-20260831/vulnerability-review.json`

## Release hardening now present

- Exact runtime and native/build-component license inventory.
- Deterministic `LICENSE.txt`, source/relink record, consolidated third-party
  notices, and hash-bound legal manifest generation and verification.
- Exact clean-commit `git archive` source ZIP, included in checksums,
  Defender scanning, release evidence, workflows, installer payload, and
  staging inventory.
- Fail-closed distribution preflight when any owner license/IP decision is
  unresolved.
- Explicit unsigned build/staging mode that does not bypass Ed25519 updater
  metadata, Defender, SBOM, vulnerability review, provenance, or exact-byte
  runtime/manual gates.

## Blocking decisions and external gates

1. **Project distribution terms.** The exact PyQt6 6.11.0 and
   PyQt6-WebEngine 6.11.0 metadata says `GPL-3.0-only`. The no-purchase path
   therefore needs the copyright owner's explicit approval to release DupeZ
   under GPL-3.0-only, followed by a real root `LICENSE.txt` and reconciliation
   of the current proprietary/open-source wording. This status record is not
   that approval.
2. **License/IP evidence.** All six decisions in
   `packaging/license-policy.json` intentionally remain unresolved. Source
   preflight passes with six warnings; distribution preflight fails with six
   blocking errors.
3. **Clean provenance.** The working tree is heavily modified. A real RC must
   be committed, independently reviewed, and rebuilt from the exact clean
   `main` commit. The private dirty snapshot cannot be promoted.
4. **Repository governance.** The latest authenticated audit found no `main`
   branch protection/ruleset, no protected independent production reviewer,
   and no governance-ready repository variable. Only the owner account is a
   collaborator. An existing independent reviewer/account is required; this
   work does not require creating or purchasing an account, but it cannot be
   manufactured locally.
5. **GitHub Actions availability.** All 14 pull-request checks for the exact
   candidate head failed before checkout with zero executed steps and no
   assigned runner. GitHub's check annotations state: `The job was not started
   because your account is locked due to a billing issue.` This is an external
   account/infrastructure block, not a test result. No paid remediation was
   attempted, and the failures must not be relabelled as passing checks.
6. **Exact-byte validation.** Compat Administrator lifecycle, exact-commit
   hardware evidence, the full manual installer/upgrade/uninstall walkthrough,
   and draft download/hash verification remain mandatory on the final rebuilt
   bytes.
7. **Unsigned route limitation.** Avoiding a paid Authenticode certificate is
   supported and clearly disclosed, but Windows will show unknown-publisher
   warnings and the production updater will not auto-execute that installer.
   The unsigned RC is manual download/install only.

## Fastest no-purchase path

After explicit owner approval of GPL-3.0-only terms, record and hash the six
license/IP determinations, create a reviewed clean `main` commit, build with
`scripts/finalize_release.ps1 -Version 5.8.0 -AllowUnsigned`, and complete the
GPU, Compat, hardware, manual, and draft verification sequence in
`BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md`. Until those gates pass, label every
generated binary as private engineering evidence, not a release candidate.
