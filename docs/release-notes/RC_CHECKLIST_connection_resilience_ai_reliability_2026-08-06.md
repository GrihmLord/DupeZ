# Release Candidate Checklist - connection_resilience_ai_reliability

Date: 2026-08-06
Branch intent: bounded resilience diagnostics, strict backend capability routing, AI reliability hardening, and release-gate consistency.

## 0. Scope and branch freeze
- Confirm only intended files are modified before cut.
- Confirm no emergency debug toggles, test bypasses, or local-only endpoint changes remain.
- Confirm version/update metadata is aligned for the planned release tag.

## 1. Capability and routing safety
- Verify request capability resolution is deterministic and fail-closed.
- Verify standard effects route to Kalirenegade backend only.
- Verify DupeZ namespaced extensions route to Native extension backend only.
- Verify mixed standard plus extension requests are rejected before launch.
- Verify explicit native preference does not override standard-effect ownership.

Evidence files:
- app/firewall/clumsy_network_disruptor.py
- app/firewall/direct_clumsy_manager.py
- app/firewall/modules/__init__.py
- app/firewall/native_divert_engine.py
- app/core/validation.py

## 2. Bounded resilience behavior
- Verify lag_max_active_ms is clamped to <= 29000 and fails open after expiry.
- Verify backlog release occurs on bounded-expiry path.
- Verify keepalive cadence is direction-aware and explicit only (never inferred).
- Verify queue overflow is fail-open, with telemetry counters incremented.

Evidence files:
- app/firewall/modules/lag.py
- app/core/builtin_presets.py
- app/core/validation.py

## 3. Godmode extension path and isolation
- Verify only namespaced extension method is used: dupez.godmode.
- Verify legacy non-namespaced module is not publicly routed.
- Verify bounded preset remains <= 29000ms and marked experimental.

Evidence files:
- app/firewall/modules/__init__.py
- app/core/builtin_presets.py
- app/core/preset_store.py
- tests/test_disruption_presets.py

## 4. AI and reliability hardening
- Verify recorder filename/session safety and collision resistance.
- Verify learning-loop profile/goal bucketing and contamination isolation.
- Verify network profiling fallback returns safe degraded profile on probe exception.
- Verify advisor fallback parser is deterministic and no-action on unclear commands.
- Verify configured secure advisor is shared with voice panel.
- Verify smart panel session lifecycle ends cleanly and exactly once.

Evidence files:
- app/ai/episode_recorder.py
- app/ai/learning_loop.py
- app/ai/llm_advisor.py
- app/ai/network_profiler.py
- app/ai/smart_engine.py
- app/gui/panels/ai_panel.py
- app/gui/panels/smart_mode_panel.py
- app/gui/panels/voice_panel.py
- app/gui/clumsy_control.py

## 5. Release and startup robustness
- Verify Authenticode preflight compatibility path remains stable under Python-launched PowerShell.
- Verify offscreen/no-tray startup path does not register global tray hotkeys.
- Verify startup smoke path passes with DUPEZ_DISABLE_WEBENGINE=1.

Evidence files:
- scripts/release_preflight.py
- app/gui/dashboard.py

## 6. Test gates
Executed and passing on this branch:
- Focused reliability suite: 61 passed, 1 skipped.
- Routing and manager policy suite: 121 passed.
- Targeted blocker re-check: 109 passed.
- Full suite: 1293 passed, 8 skipped.

Required pre-cut reruns:
- pytest -q
- pytest -q tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_disruption_presets.py
- pytest -q tests/test_active_content_safety.py tests/test_gui_startup_smoke.py

## 7. Hardware and privileged validations (manual/opt-in)
- Run opt-in hardware smoketests on prepared Windows host with explicit authorized targets.
- Verify real driver and adapter behavior for bounded lag and extension selection.
- Verify no stale helper or clumsy process remains after start/stop cycles.

## 8. Packaging and artifact integrity
- Build GPU and Compat variants.
- Verify installer build and release sidecars.
- Verify release-preflight checks pass end-to-end.
- Verify artifact hashes and signature checks align with release metadata.

## 9. Documentation and user-facing consistency
- Ensure user-facing notes describe bounded diagnostics and strict backend routing accurately.
- Ensure no residual prohibited active-content language appears in active shipped files.
- Ensure roadmap/release notes explicitly state fail-closed behavior and extension boundaries.

## 10. Release decision criteria
Ship only if all are true:
- Full automated suite is green on the intended release commit.
- No critical/high unresolved regression findings remain.
- Manual hardware checks are either passed or explicitly deferred with accepted risk.
- Packaging and signature verification pass on exact artifacts.
- Changelog and release-notes delta match shipped behavior exactly.
