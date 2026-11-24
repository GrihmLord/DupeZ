# SUPPLY_CHAIN_ASSESSMENT

- The current-tree source preflight and CI-equivalent source gate passed on
  CPython 3.13.14 x64.
- Exact current-tree distribution artifacts have not been rebuilt and validated;
  existing `dist` contents are not current release evidence.
- The saved authenticated 2026-08-28 read-only GitHub API audit found `main`
  unprotected with zero repository rulesets, `production-release` with no
  protection rules or deployment-branch policy, and
  `DUPEZ_RELEASE_GOVERNANCE_READY` absent. Signing/finalization remains blocked
  until those controls are configured and API-verified, in addition to the
  elevated host and signing inputs required by the artifact flow. Evidence:
  `assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-08-28.json`.
