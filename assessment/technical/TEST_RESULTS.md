# TEST_RESULTS

## Executed in this assessment
- pytest -q tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_disruption_presets.py
  - Result: 121 passed
- pytest -q tests/test_active_content_safety.py tests/test_gui_startup_smoke.py
  - Result: 2 passed
- pytest -q
  - Result: 1293 passed, 8 skipped

## Notes
- Skipped tests are expected opt-in hardware/platform constrained checks.
