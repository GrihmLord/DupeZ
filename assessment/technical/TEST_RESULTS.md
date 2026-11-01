# TEST_RESULTS

## Current-tree evidence (2026-08-28)
- Source identity: uncommitted working tree based on `main@77fb1d8`; this is
  not evidence for an exact committed SHA.
- Full tests / CI-equivalent source gate, CPython 3.13.14 x64:
  - Command: `.test-venv-313\Scripts\python.exe -X faulthandler -m pytest tests -q --maxfail=5 --cov=app --cov-report=term --cov-fail-under=40`
  - Result: 2110 passed, 10 expected skips; 53.02% application coverage
    against the 40% CI floor; 133.77s.
  - Skip breakdown: 3 opt-in Clumsy hardware tests; 3 redactor tests requiring
    symlink privilege; 3 opt-in hardware-smoketest tests; 1 installer symlink
    test.
- Source release preflight for v5.8.0 and the consolidated source-policy gates:
  passed (E-008).

## Historical executions (superseded)
The following results predate the final current-tree gate. They remain
historical diagnostic evidence and are not the current aggregate result.

- pytest -q tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_disruption_presets.py
  - Result: 121 passed
- pytest -q tests/test_active_content_safety.py tests/test_gui_startup_smoke.py
  - Result: 2 passed
- .venv\\Scripts\\python.exe -X faulthandler -m pytest tests -q --maxfail=5 --cov=app --cov-report=term --cov-fail-under=40
  - Result (2026-08-14 v5.8.0 source candidate): 1538 passed, 7 expected opt-in/host-capability skips; 46.39% coverage
- python scripts/release_preflight.py --version 5.8.0
  - Result: Release preflight passed
- pytest -q tests/test_engine_supervisor.py tests/test_disruption_generation_guard.py tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_capability_routing.py tests/test_godmode_extension.py tests/test_llm_advisor_safety.py
  - Result: 136 passed
- python bench/latency_regression.py --iters 10000 --path both
  - Result: split/loopback hotkey p999 0.180 ms; target is below 1 ms
- app.core.performance_smoke.run_performance_smoke(iterations=20)
  - Result: all checks passed; traffic analyzer 2000-record p95 1.879 ms against 50 ms budget
- Native stderr/zero-exit Administrator wrapper simulation
  - Result: passed; logged native diagnostics no longer override a successful finalizer exit code
- Cross-UAC Local AppData override simulation
  - Result: passed; isolated GUI environment and elevated helper resolve one canonical auth sentinel
- Nested blocked-gate failure policy
  - Result: passed; child nonzero exit is captured immediately and raised by the sequencer
- Win64 frozen-input ABI and elevated-helper cleanup regression
  - Result: passed; native `INPUT` is 40 bytes, access denial cannot mask the triggering failure, and recreated/foreground-locked Qt HWNDs are rebound and activated
- Noninteractive variant-build failure policy
  - Result: passed; no canonical batch failure path can wait at `pause`

## Notes
- The 10 skipped tests are the expected opt-in/host-capability checks itemized
  above and are not exact-artifact evidence.
- The final full tests and CI-equivalent source gate ran on CPython 3.13.14
  x64. The repository CI matrix remains Python 3.12/3.13.
- Local `.venv` and the currently materialized `.release-venv` are Python
  3.11.9. The latter is stale/noncanonical and is not packaging evidence;
  canonical builds must recreate `.release-venv` with CPython 3.13.14 x64.
