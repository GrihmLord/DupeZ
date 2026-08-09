# Release Notes Delta - connection_resilience_ai_reliability

Date: 2026-08-06
Scope: delta only for current branch changes.

## Summary
This branch upgrades disruption routing to a strict capability-owned model, restores bounded private-network resilience diagnostics, reintroduces a namespaced bounded pulse extension path, hardens AI and learning reliability, and closes release/test gate regressions.

## Added
- New bounded built-in diagnostics:
  - Connection Resilience Lab using dupez.custom_lag.
  - Pulse Resilience Lab (Experimental) using dupez.godmode.
- Explicit native-extension parameter ranges for bounded operation windows and extension controls.
- Process-wide packet-owner leases with exact generation, backend, capability,
  capture-layer, and filter-fingerprint status.
- Additional reliability-focused regression coverage across presets, routing policy, startup smoke, and AI/session lifecycle paths.

## Changed
- Backend routing is deterministic and fail-closed:
  - Standard effects are Kalirenegade-owned.
  - DupeZ namespaced extensions are native-extension-owned.
  - Mixed requests are rejected pre-launch.
  - Automatic fallback from failed Clumsy start to native substitution is removed.
- Lag module behavior is now explicitly bounded for resilience diagnostics:
  - max active window clamp at 29000ms.
  - expiry flush and fail-open release behavior.
  - direction-aware keepalive cadence.
  - explicit queue-overflow telemetry.
- Smart panel profiling now passes device metadata into async profile calls.
- Voice panel now uses the configured secure advisor injected by AI panel.
- Offscreen/no-tray startup now skips tray hotkey registration.
- The bounded pulse extension now honors direction, distinguishes TCP payload
  from control traffic, reports the new telemetry schema in Live Stats, and
  fails open on scheduler errors.

## Fixed
- Preset mapping consistency:
  - Standard Lag uses lag.
  - Connection Resilience Lab uses dupez.custom_lag.
  - legacy custom-preset `ooo` values migrate to canonical `ood`.
  - mixed standard/extension presets are rejected during save/import.
- AI reliability and safety:
  - recorder collision-safe filename/session handling.
  - learning-loop bucket contamination safeguards.
  - network profiler robust fallback profile on probe failures.
  - unclear advisor prompts return no-action clarification output.
- Release/test gate blockers:
  - active-content safety wording regressions removed from active shipped surfaces.
  - dashboard offscreen startup smoke failure resolved.
  - Authenticode preflight PowerShell module load path hardened.

## Security and policy posture
- Enforces strict ownership boundaries between standard effects and native extensions.
- Removes silent backend substitution behavior in AUTO mode.
- Maintains bounded (<30s) resilience windows for dedicated diagnostics.
- Treats remote AI output as untrusted: hidden routing keys and undeclared
  parameters are stripped before capability planning.

## Validation results on current continuation branch
- Full repository suite: 1319 passed, 8 expected hardware/platform skips.
- Source release preflight: passed for version 5.7.9.
- Focused ownership/routing/extension suite: 136 passed.
- Active-content/startup/preset/release-policy gate: 52 passed.

## File groups touched
- AI reliability: app/ai/*
- Core presets and validation: app/core/builtin_presets.py, app/core/preset_store.py, app/core/validation.py
- Firewall routing and modules: app/firewall/clumsy_network_disruptor.py, app/firewall/direct_clumsy_manager.py, app/firewall/modules/__init__.py, app/firewall/modules/lag.py, app/firewall/native_divert_engine.py
- GUI integration: app/gui/clumsy_control.py, app/gui/dashboard.py, app/gui/panels/ai_panel.py, app/gui/panels/smart_mode_panel.py, app/gui/panels/voice_panel.py
- Release preflight: scripts/release_preflight.py
- Regression tests: tests/test_* (routing, presets, reliability)
