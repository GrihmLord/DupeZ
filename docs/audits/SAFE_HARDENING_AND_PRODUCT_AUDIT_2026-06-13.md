# DupeZ Safe Hardening and Product Audit - 2026-06-13

## Scope

This audit covers safe reliability, security, maintainability, observability,
and user-control improvements for the current DupeZ codebase. It explicitly
excludes work that would improve exploit success, game cheating, bypass attempts against
server-integrity systems, unauthorized disruption, or operation against devices outside the authorized lab.

Evidence baseline:

- Full lint gate: `python -m ruff check .` passes.
- Full test gate: `python -m pytest -q` passes with 834 passed, 4 skipped.
- Local offsec vuln discovery: 0 critical, 0 high, 0 medium, 0 low findings;
  only the invocation metadata record remains.
- Subprocess hardening now centralizes one-shot, detached, and managed long-running
  child process creation through `app.core.safe_subprocess`.

## Changes Completed In This Pass

1. Centralized subprocess policy for long-running helper processes.
   `safe_subprocess.spawn_managed()` returns a bounded process wrapper with
   `pid`, `poll()`, `kill()`, and `returncode`, while preserving argv validation,
   `shell=False`, hidden Windows startup info, `close_fds=True`, stdio redirection,
   and audit events.

2. Moved the fallback `clumsy.exe` lifecycle onto `spawn_managed()`.
   The fallback engine still gets the process handle it needs, without direct
   `subprocess.Popen()` calls in feature code.

3. Routed ping and ARP utility calls through `safe_subprocess`.
   Scanner, cut-verifier, and shared helper ping paths now use central policy
   on Windows and POSIX.

4. Reduced static scanner noise.
   Vendored clumsy source is excluded from first-party source-smell findings,
   and a log message that matched as code was reworded.

5. Fixed an offsec runner correctness bug.
   The second-factor gate now receives the selected tactic list after it is
   computed, not before.

6. Added a local VEX placeholder artifact.
   `dist/DupeZ.vex.json` exists with an empty `statements` list so the local
   static checker can distinguish "no affected statements asserted" from
   "VEX file missing".

7. Added local privacy inventory and scrub tooling.
   `app.core.privacy` inventories audit logs, episode telemetry, device caches,
   scheduler metadata, and optional account/profile data. The CLI exposes
   `privacy scan` and `privacy scrub --apply`, quarantining by default.

8. Added safe CLI maintenance commands that do not require Administrator.
   `diagnostics`, `privacy`, and `recovery` run without initializing the packet
   engine. Active commands such as `scan`, `status`, `disrupt`, and `stop` still
   require Administrator.

9. Added release VEX skeleton generation.
   `scripts/vex.py` builds an OpenVEX-style dependency review skeleton from
   `requirements-locked.txt` with `under_investigation` statements that release
   reviewers can replace with vulnerability-specific assertions.

10. Promoted integrity substrate checks into diagnostics.
    `diagnostics` now reports secret-store accessibility, persistence HMAC key
    degradation, and audit-chain sealed/degraded/verification state with
    operator-facing recovery hints.

11. Added focused secret-store recovery status.
    `recovery secret-store-status` reports reachability, writability, and the
    exact access error without initializing packet engines or audit recovery
    flows.

12. Added machine-readable safe maintenance output.
    `diagnostics`, `privacy scan`, `privacy scrub`, `recovery audit-status`,
    and `recovery secret-store-status` now support `--json` for automation,
    support bundles, and future GUI health panels.

13. Added source leak guards for secrets and personal IP exposure.
    `tests/test_source_leak_guard.py` scans tracked and source-tree text files
    for high-confidence credential patterns and unapproved public IPv4 literals.
    The secret-scan workflow now runs this guard, and a real-looking public
    server placeholder was replaced with a documentation-reserved address.

14. Improved safe DayZ user workflows.
    The account tracker now has reusable DayZ-aware filters for status,
    station/kit, inferred map, needs state, value bucket, and full-text search.
    Diagnostics also includes a passive WiFi adapter-path check so users can
    see whether the default route appears wireless without changing network
    behavior.

## Safe Major Improvement Roadmap

### P0 - User Safety and Scope Controls

- Add a first-run safety mode requiring explicit acknowledgement that the tool is
  for owned lab networks and local testing only.
- Add a session scope lock: the operator must select an allowed CIDR/device list
  before any active network operation can run.
- Add a global dry-run mode that exercises controller, UI, audit, and scheduling
  flows without packet manipulation.
- Add a hard maximum duration and automatic restore for every active operation.
- Add a visible "all operations stopped and network state restored" post-stop
  confirmation.

### P1 - Reliability Without Abuse Amplification

- Improve recovery after process crash: persist enough local state to restore
  firewall rules, IP forwarding state, and helper process state on next launch.
- Expand diagnostics around WinDivert/Npcap availability, admin rights, driver
  version, and helper health.
- Add packet-engine lifecycle tests that mock handles and verify cleanup paths.
- Add structured error codes for UI, CLI, and logs so failures are actionable.

### P2 - Privacy and Local Data Hygiene

- Add a privacy scrub command that redacts or deletes local `app/data` runtime
  telemetry, audit archives, device caches, and account export remnants.
- Add an in-app data inventory view showing what local files exist and why.
- Add retention configuration for audit, episodes, backups, and diagnostics.
- Make every export path opt-in and show whether it may contain IPs, MACs, or
  account notes.

### P3 - Supply Chain and Release Integrity

- Generate SBOM and VEX artifacts in the release workflow.
- Use `scripts/sbom.py` and `scripts/vex.py` as the default local generators.
- Fail release builds if the VEX file is missing, invalid JSON, or contains an
  `affected` statement without an action statement.
- Add dependency update review notes for every runtime package bump.
- Add a release preflight that verifies signature keys, updater pins, installer
  metadata, and build artifacts.

### P4 - Plugin Safety

- Add plugin permission review UI before activation.
- Add plugin capability tests for filesystem, process, network, and dynamic-code
  denial paths.
- Add plugin quarantine for repeated sandbox violations.
- Add signed-plugin developer tooling that produces clear validation errors.

### P5 - Product Features That Are Safe To Build

- "Lab Simulator" mode: replay recorded synthetic packet events into the UI and
  analytics without touching the network.
- "Network Health Dashboard": passive local diagnostics, latency trends, adapter
  health, driver state, and configuration drift.
- "Recovery Center": one-click reset for audit seal, temp test directories,
  stale helper processes, and local config integrity problems.
- "Evidence Pack Export": redacted ZIP for bug reports containing version,
  config metadata, diagnostics, and scrubbed logs.
- "Accessibility Pass": keyboard-first navigation, high-contrast status states,
  and safer confirmation dialogs.

## Explicit Non-Goals

The following are not safe improvement areas and should not be implemented:

- Better game-dupe timing, success rate, or exploit reliability.
- Anti-cheat evasion, bypass tuning, or process-name evasion.
- Deauthentication, credential capture, or unauthorized traffic disruption.
- Features that target devices outside an owned and explicitly scoped lab network.
- Documentation that teaches exploitation against public games or third parties.

## Current Blockers

- Runtime secret store access is denied at
  `C:\Users\Owner\AppData\Local\DupeZ\secrets` during local test runs, causing
  fallback key behavior in logs. This is a machine ACL issue, not a repo test
  failure.
- Hardware validation remains skipped unless run on an elevated Windows host with
  WinDivert/Npcap and an owned test target.
- The VEX file added in this pass is a local placeholder. Release VEX should be
  generated from the release SBOM and actual dependency vulnerability review.
