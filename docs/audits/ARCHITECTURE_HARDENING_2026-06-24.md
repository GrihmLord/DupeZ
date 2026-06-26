# Architecture Hardening Audit - 2026-06-24

## Scope

This pass reviewed Python package boundaries, import-time coupling, module size,
global state, and supportability. It did not expand packet disruption or other
active network capabilities.

## Measured findings

- The largest orchestration/view modules remain concentrated in
  `app/gui/clumsy_control.py`, `app/firewall/clumsy_network_disruptor.py`,
  `app/gui/dayz_account_tracker.py`, `app/firewall/native_divert_engine.py`,
  and `app/gui/dashboard.py`.
- Several services are constructed as import-time singletons. This increases
  startup coupling and makes safe maintenance commands more vulnerable to
  unrelated infrastructure failures.
- Two dependency inversions were present:
  - `app.core.cut_chain` imported preset data from a Qt GUI module.
  - `app.firewall_helper.feature_flag` imported GPU probing from the GUI map
    renderer package.

## Completed reinforcements

1. Moved built-in preset ownership to `app/core/builtin_presets.py`.
2. Updated the GUI to expose a compatibility alias while consuming backend
   preset data.
3. Updated cut-chain orchestration to resolve defensive preset copies without
   importing Qt.
4. Added `app/core/gpu_probe.py` as a GUI-independent capability probe.
5. Updated the helper architecture selector to use the core GPU probe.
6. Added AST-based dependency guards preventing `app.core` and
   `app.firewall_helper` from importing `app.gui`.
7. Updated doc-drift tests so backend preset definitions are the source of
   truth.
8. Removed import-time disruption-manager construction from
   `app/core/controller.py`.
9. Added explicit controller dependency injection for disruption, persistence,
   state, scheduler, and plugin services.
10. Added idempotent `start()` and `shutdown()` lifecycle methods while
    preserving production auto-start behavior.
11. Replaced auto-scan interval sleeping with an event-driven stop and bounded
    thread join, preventing controller shutdown from leaving a sleeping worker.
12. Added lifecycle and AST regression tests for service ownership and
    import-time side effects.
13. Added startup rollback so partial scheduler/scan failures do not leave the
    disruption engine running.
14. Isolated shutdown steps so one failing plugin or service cannot prevent
    cleanup of the remaining controller-owned resources.

## Recommended next sequence

1. Continue replacing import-time manager construction with lazy provider
   functions, beginning with data persistence and update checking.
2. Split `clumsy_network_disruptor.py` by responsibility: engine lifecycle,
   target policy, process fallback, and event reporting.
3. Split `clumsy_control.py` into view-model/state adapters and focused widgets.
4. Define typed protocols for controller, disruption engine, and diagnostic
   providers to reduce private-attribute polling.
5. Add architecture guards for additional stable boundaries after existing
   reverse imports in `logs`, `utils`, and `network` are deliberately removed.

Each step should preserve behavior and land with focused regression tests before
the next boundary is tightened.
