# SECURITY_ASSESSMENT

- Assessed deterministic capability ownership model in disruption routing.
- Verified fail-closed behavior via policy suites.
- Verified that redirect handling remains denied by the generic secure HTTP
  client and is narrowly implemented for updater release assets with exact,
  query-free GitHub alias/tag paths and an alias-to-same-repository/tag/
  filename-to-exact-CDN state machine capped at two hops. Lookalike/private
  targets, extra hops, encoded separators, loops, malformed targets, and
  URL-bearing transport failures are rejected; cross-origin headers are
  stripped and the signed-content and Windows provenance gates are unchanged.
- Verified that isolation-watchdog cancellation and callback delivery now have
  a lock-linearized outcome: cancel-first delivers `ABORTED`; delivery-first
  requires bounded worker/callback quiescence, with timeout surfaced rather
  than silently accepted and self-cancel protected from self-join.
- Verified that JUnit release evidence requires strict UTF-8 and rejects DTD
  and entity declarations before XML parsing.
- Verified the model-load authentication boundary with real HMAC-SHA384
  regression cases that cannot reach `pickle.loads` until verification
  succeeds; the unsafe-deserialization suppression is limited to that guarded
  call site.
- A local-only detect-secrets 1.5.0 comparison covered all 931 tracked files
  and 48 scoped nonignored untracked source/configuration/documentation files:
  all 31 explicitly audited public-key, provenance, manifest, documentation,
  and synthetic-test findings were rediscovered, with zero unaudited findings.
- Fresh Bandit review reported 0 high, 13 reviewed medium false positives, and
  214 low findings. No medium/high true positive remains; the guarded XML
  parser warning and updater log-string heuristic are covered by focused
  boundary tests.
- Active offensive validation not executed (no explicit authorization in this session).
- Dist artifact authenticity checks failed in current state due unsigned/missing release sidecars.
- The saved authenticated read-only GitHub API audit on 2026-08-28 found no
  branch protection or ruleset on `main`, no protection rules or
  deployment-branch policy on `production-release`, and no
  `DUPEZ_RELEASE_GOVERNANCE_READY` repository variable. Workflow-local guards
  cannot substitute for these server-side release-boundary controls, so both
  release workflows remain blocked. Evidence:
  `assessment/evidence/GITHUB_GOVERNANCE_AUDIT_2026-08-28.json`.
