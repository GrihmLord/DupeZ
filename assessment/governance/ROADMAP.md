# ROADMAP

Review mandate: RELEASE_ASSURANCE
Transaction stage: NOT_APPLICABLE
Reference revision: uncommitted working tree based on main@77fb1d8
Evidence cutoff: 2026-08-28 UTC
Execution mode: local evidence-driven assessment
Environment: Windows + CPython 3.13.14 x64 full tests/CI-equivalent source
gate. Local `.venv` and existing `.release-venv` are 3.11.9; the latter is
stale/noncanonical and canonical builds must recreate it with 3.13.14.

## Phase Status
- Phase 0: COMPLETE | Mandate, scope, authorization, and capability preflight recorded
- Phase 1: PARTIAL | Repository-local evidence indexed; corporate/data-room evidence pending
- Phase 2: PARTIAL | Product/transaction claims recorded with unverified non-technical claims
- Phase 3: COMPLETE | System/surface inventory completed for in-scope workspace
- Phase 4: PARTIAL | Code and config sensitive-data scan only; history and legal IP chain pending
- Phase 5: PARTIAL | Source QA passed; server-side governance and exact policy-conforming artifact lifecycle tests blocked
- Phase 6: PARTIAL | Architecture and code-quality review completed on changed/high-risk areas
- Phase 7: PARTIAL | Latency regression and source performance smoke pass; frozen-artifact profiling pending
- Phase 8: PARTIAL | Threat and boundary review completed; no active exploit validation
- Phase 9: PARTIAL | Data/privacy technical paths reviewed; legal basis mapping pending
- Phase 10: PARTIAL | AI/agent reliability and control-path checks executed from code and tests
- Phase 11: PARTIAL | SBOM/provenance controls present; server-side release governance and final artifact integrity blocked
- Phase 12: PARTIAL | Reliability/recovery reviewed with test evidence; DR failover not executed
- Phase 13: BLOCKED | No explicit authorization for active security validation in this session
- Phase 14: PARTIAL | Accessibility/compatibility only partially evidenced via smoke and code review
- Phase 15: PARTIAL | Legal/IP/contract support structure created; specialist evidence not provided
- Phase 16: PARTIAL | Commercial/financial/vendor/insurance data not provided
- Phase 17: PARTIAL | Framework applicability drafted; specialist compliance determinations pending
- Phase 18: PARTIAL | Competitive analysis available from repository docs only
- Phase 19: PARTIAL | Integration/separation planning drafted; transaction specifics unavailable
- Phase 20: PARTIAL | Risk register updated with the live unprotected-repository finding
- Phase 21: PARTIAL | Code/test remediation executed; required GitHub protections remain absent
- Phase 22: PARTIAL | Source gate complete; repository governance and exact artifact gates blocked

Current phase: Phase 22 (final packet assembly)
Open blockers:
- A read-only GitHub API inspection on 2026-08-28 found no branch protection
  or ruleset on `main`, and no protection rules or deployment-branch policy on
  `production-release`. Both release workflows remain blocked; repository-local
  guards and `DUPEZ_RELEASE_GOVERNANCE_READY` are defense in depth only. The
  variable is also absent in the saved 2026-08-28 evidence.
- Standard staged-child signing and the explicitly attested unsigned exception
  are implemented, but no new exact policy-conforming artifacts have been
  produced or exercised on the protected release host.
- v5.8.0 exact artifacts must be rebuilt from reviewed, clean main after the
  server-side controls are configured and API-verified.
- Frozen GPU/Compat evidence, manual walkthrough, and staging are not yet complete.
Open regressions:
- None in the current-tree automated suite; 2110 passed, with 10 expected
  skips (3 opt-in Clumsy hardware, 3 symlink-privilege redactor, 3 opt-in
  hardware-smoketest, and 1 installer symlink), 53.02% coverage, and a
  133.77s runtime on CPython 3.13.14 x64.
Evidence requests:
- Corporate/legal/financial/insurance records not provided in this workspace.
Conflicted evidence:
- Repository documents correctly require protected `main` and a reviewed
  `production-release` environment, but the live 2026-08-28 API inspection
  found both server-side controls absent.
Unverified areas:
- Server-side repository governance remediation and exact policy-conforming
  artifact distribution validation/publish workflow.
Specialist referrals:
- Legal/IP/compliance/insurance determinations.
Next action:
- Configure and API-verify `main` branch protection/rulesets and
  `production-release` protection/deployment policy, then set the governance
  variable and proceed through exact-head merge and the protected artifact flow.
