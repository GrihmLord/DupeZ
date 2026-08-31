# CHAIN_OF_CUSTODY

- The assessed source was first recorded on 2026-08-21 as an uncommitted,
  mutable working tree based on `main@77fb1d8`; no exact committed snapshot is
  claimed for the 2026-08-28 gate.
- The CPython 3.13.14 x64 CI-equivalent full source gate completed on
  2026-08-28 with 2110 passed, 10 expected skips, 53.02% coverage, and
  133.77 seconds elapsed. The skips were 3 opt-in Clumsy hardware tests,
  3 redactor tests requiring symlink privilege, 3 opt-in hardware-smoketest
  tests, and 1 installer symlink test.
- Gate command: `.test-venv-313\Scripts\python.exe -X faulthandler -m pytest tests -q --maxfail=5 --cov=app --cov-report=term --cov-fail-under=40`.
- The same current tree passed the v5.8.0 source preflight, Ruff and AST over
  397 Python files, all four hashed-lock contracts, three PowerShell release
  contracts, and `git diff --check`. A no-network-verification secret scan over
  931 tracked plus 48 scoped nonignored untracked files rediscovered all 31
  explicitly audited false positives with zero unaudited findings. Fresh
  Bandit review found zero high findings and no medium/high true positive.
- An authenticated read-only GitHub API inspection on 2026-08-28 observed no
  branch protection or ruleset on `main`, no protection rules or
  deployment-branch policy on `production-release`, and no
  `DUPEZ_RELEASE_GOVERNANCE_READY` repository variable.
- The minimized, credential-free observation is preserved as
  `assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-08-28.json`.
- No product source evidence was overwritten during these assessment-register updates.
