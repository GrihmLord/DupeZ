# DISTRIBUTION_READINESS

Current status: BLOCKED

Blocking items:
- The saved authenticated read-only GitHub API audit on 2026-08-28 found no
  branch protection or ruleset on `main`, no protection rules or
  deployment-branch policy on `production-release`, and no
  `DUPEZ_RELEASE_GOVERNANCE_READY` repository variable. Both release workflows
  remain blocked; repository-local guards are defense in depth only. Evidence:
  `assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-08-28.json`.
- Exact current-tree release artifacts, signed updater metadata, frozen
  GPU/Compat evidence, and installer lifecycle evidence remain pending.
- After server-side controls are API-verified, protected staging still requires
  reviewed clean `main`, the exact validated artifacts, and authorized inputs.
