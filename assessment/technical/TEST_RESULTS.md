# TEST_RESULTS

## Executed in this assessment
- pytest -q tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_disruption_presets.py
  - Result: 121 passed
- pytest -q tests/test_active_content_safety.py tests/test_gui_startup_smoke.py
  - Result: 2 passed
- pytest -q
  - Result (2026-08-08 continuation): 1319 passed, 8 skipped
- python scripts/release_preflight.py --version 5.7.9
  - Result: Release preflight passed
- pytest -q tests/test_engine_supervisor.py tests/test_disruption_generation_guard.py tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_capability_routing.py tests/test_godmode_extension.py tests/test_llm_advisor_safety.py
  - Result: 136 passed

## Notes
- Skipped tests are expected opt-in hardware/platform constrained checks.
