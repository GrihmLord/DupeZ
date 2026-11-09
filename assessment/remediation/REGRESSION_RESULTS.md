# REGRESSION_RESULTS

- Full tests / CI-equivalent source gate (2026-08-28, CPython 3.13.14 x64):
  2110 passed, 10 expected skips; 53.02% application coverage (40% CI floor);
  133.77s. The skips were 3 opt-in Clumsy hardware tests, 3 redactor tests
  requiring symlink privilege, 3 opt-in hardware-smoketest tests, and
  1 installer symlink test. Source identity is the uncommitted working tree
  based on `main@77fb1d8`, not an exact committed SHA.
- Authoritative command: `.test-venv-313\Scripts\python.exe -X faulthandler -m pytest tests -q --maxfail=5 --cov=app --cov-report=term --cov-fail-under=40`.
- Superseded focused results retained only as historical diagnostics:
  routing/policy 121 passed; startup/content safety 2 passed.
- Source release preflight for v5.8.0: passed on the current tree.
- Added coverage for canonical request planning, process-wide packet ownership,
  bounded pulse-extension lifecycle, AI parameter safety, and preset migration.
- Added coverage for bounded provider concurrency, asynchronous traffic snapshot
  coalescing/read safety, release-state version isolation, and PowerShell 5.1 lock parsing.
- Added updater release-asset coverage for the API-preferred tagged installer,
  the versionless fallback alias, and both signed sidecars: exact
  alias-to-same-repository/tag/filename-to-CDN sequencing, the production
  two-hop ceiling, sensitive-header stripping, URL-free transport failures,
  closed intermediate responses, lookalike/private/malformed/loop rejection,
  and the `download_and_install` path. The shared secure HTTP redirect-refusal
  regressions remain in force.
- Added deterministic isolation-watchdog race coverage proving cancel-first
  delivery becomes `ABORTED`, committed callbacks quiesce or time out within a
  bound, event cancellation wakes promptly, and self-cancel does not deadlock.
- Added JUnit evidence-ingestion regressions for strict UTF-8 decoding and
  pre-parse rejection of DTD and entity declarations.
- Added model-integrity regressions that use a real HMAC-SHA384 tag, observe
  verification completing before `pickle.loads`, and prove missing, malformed,
  incorrect, or artifact-mismatched authentication never invokes unpickling.
- Repaired the logged Administrator wrapper so native stderr remains evidence
  while the nested finalizer exit code remains the release decision.
- Repaired split-helper token discovery across UAC environment boundaries and
  made nested blocked-gate failures propagate to the launcher state.
- Repaired the Win64 frozen-input ABI and made failure cleanup tolerate the
  expected access boundary around the High-Integrity helper; runtime shortcut
  checks now rebind a Qt dashboard handle recreated during lazy Map startup and
  attach Windows input queues when foreground locking prevents activation.
- Removed all interactive pauses from canonical variant-build failures so
  protected finalizers return the actionable error immediately.
