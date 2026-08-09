# REGRESSION_RESULTS

- Full suite (2026-08-09 v5.8.0 candidate): 1328 passed, 8 expected opt-in/platform skips.
- Routing/policy suite: 121 passed.
- Startup/content safety gate: 2 passed.
- Source release preflight for v5.8.0: passed.
- Added coverage for canonical request planning, process-wide packet ownership,
  bounded pulse-extension lifecycle, AI parameter safety, and preset migration.
- Added coverage for bounded provider concurrency, asynchronous traffic snapshot
  coalescing/read safety, release-state version isolation, and PowerShell 5.1 lock parsing.
- Repaired the logged Administrator wrapper so native stderr remains evidence
  while the nested finalizer exit code remains the release decision.
