# TEST_RESULTS

## Executed in this assessment
- pytest -q tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_disruption_presets.py
  - Result: 121 passed
- pytest -q tests/test_active_content_safety.py tests/test_gui_startup_smoke.py
  - Result: 2 passed
- pytest -q
  - Result (2026-08-09 v5.8.0 candidate): 1326 passed, 8 expected opt-in/platform skips
- python scripts/release_preflight.py --version 5.8.0
  - Result: Release preflight passed
- pytest -q tests/test_engine_supervisor.py tests/test_disruption_generation_guard.py tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_capability_routing.py tests/test_godmode_extension.py tests/test_llm_advisor_safety.py
  - Result: 136 passed
- python bench/latency_regression.py --iters 10000 --path both
  - Result: split/loopback hotkey p999 0.180 ms; target is below 1 ms
- app.core.performance_smoke.run_performance_smoke(iterations=20)
  - Result: all checks passed; traffic analyzer 2000-record p95 1.879 ms against 50 ms budget

## Notes
- Skipped tests are expected opt-in hardware/platform constrained checks and are not exact-artifact evidence.
