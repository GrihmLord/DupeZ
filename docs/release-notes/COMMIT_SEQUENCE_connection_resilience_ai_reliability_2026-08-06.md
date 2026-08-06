# Commit Sequence Plan - connection_resilience_ai_reliability

Date: 2026-08-06
Goal: produce clean, reviewable commits for next release cut.

## Commit 1 - Capability ownership and deterministic routing
Message:
- firewall: enforce capability-owned backend routing and fail-closed execution plans

Files:
- app/firewall/clumsy_network_disruptor.py
- app/firewall/direct_clumsy_manager.py
- app/firewall/modules/__init__.py
- app/firewall/native_divert_engine.py
- tests/test_clumsy_network_disruptor.py
- tests/test_direct_clumsy_manager.py
- tests/test_clumsy_engine_policy.py
- tests/test_disruption_presets.py

Intent:
- Resolve backend via capability plan before launch.
- Reject mixed/unknown/incompatible requests pre-engine start.
- Remove AUTO runtime substitution from failed Clumsy starts.

## Commit 2 - Bounded resilience and preset/validation alignment
Message:
- core+firewall: add bounded resilience presets and lag fail-open expiry controls

Files:
- app/core/builtin_presets.py
- app/core/preset_store.py
- app/core/validation.py
- app/firewall/modules/lag.py
- tests/test_builtin_presets.py

Intent:
- Introduce bounded resilience and bounded pulse extension presets.
- Enforce extension parameter range validation.
- Ensure lag expiry and bounded runtime behavior is explicit and tested.

## Commit 3 - AI reliability and session hygiene
Message:
- ai+gui: harden advisor/network profiling/session lifecycle and reliability paths

Files:
- app/ai/episode_recorder.py
- app/ai/learning_loop.py
- app/ai/llm_advisor.py
- app/ai/network_profiler.py
- app/ai/smart_engine.py
- app/gui/clumsy_control.py
- app/gui/panels/ai_panel.py
- app/gui/panels/smart_mode_panel.py
- app/gui/panels/voice_panel.py
- tests/test_regression_v350.py

Intent:
- Eliminate recorder collisions and unsafe naming edges.
- Prevent learning/profile contamination across targets/goals.
- Keep unclear prompt handling no-action and deterministic.
- Ensure voice panel uses configured secure advisor.

## Commit 4 - Release gate and startup robustness
Message:
- release+gui: harden preflight Authenticode path and offscreen startup hotkey safety

Files:
- scripts/release_preflight.py
- app/gui/dashboard.py

Intent:
- Stabilize Authenticode checks from Python-invoked PowerShell.
- Prevent offscreen/no-tray startup hook failures.

## Commit 5 - Reliability regression test additions
Message:
- tests: add focused reliability coverage for recorder, learning loop, profiler, smart sessions, and lag

Files:
- tests/test_episode_recorder_reliability.py (if present in your working tree at commit time)
- tests/test_learning_loop_reliability.py (if present in your working tree at commit time)
- tests/test_network_profiler_reliability.py (if present in your working tree at commit time)
- tests/test_smart_session_lifecycle.py (if present in your working tree at commit time)
- tests/test_lag_module.py (if present in your working tree at commit time)

Intent:
- Keep reliability fixes protected from regression.

## Suggested command flow
1) Review staging slices per commit above.
2) Run targeted suite after each commit where applicable.
3) Run full suite on final commit in sequence.
4) Tag only after exact-artifact preflight and packaging checks pass.

## Pre-tag gate
- pytest -q passes on exact release commit.
- release preflight checks pass.
- release checklist file RC_CHECKLIST_connection_resilience_ai_reliability_2026-08-06.md is signed off.
