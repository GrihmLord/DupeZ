# Deep Defensive Audit - 2026-06-24

## Scope and safety boundary

This audit covers defensive security, reliability, privacy, maintainability,
release integrity, privileged Windows execution, CI, testing, and supportability.
It does not improve game-state manipulation, server-integrity bypass, targeting, concealed operation,
or disruption of devices outside the authorized lab.

## Evidence baseline

- 994 tests pass; 10 hardware/platform/profile-specific tests are skipped.
- Ruff passes across application, tests, scripts, and entry points.
- Architecture, source-leak, documentation-drift, and YAML parsing checks pass.
- The lock file yields a 32-component CycloneDX SBOM and a 32-statement VEX
  review skeleton.
- The local secret store remains inaccessible because of host ACLs, so tests
  use the documented degraded/ephemeral key paths.

## High-priority findings fixed

1. **SSRF literal-IP validation bypass.** `validate_url()` raised `ValueError`
   for private addresses inside a `try` whose `except ValueError` then swallowed
   that rejection. Private, loopback, link-local, multicast, unspecified, and
   reserved IP literals are now rejected and regression-tested.
2. **Path containment used string prefixes.** Plugin and safe-path validation
   now use normalized `commonpath()` semantics, including cross-drive failure
   handling, rather than case-sensitive prefix comparisons.
3. **Active operations accepted arbitrary IPv4 targets.** Controller disruption
   entry now rejects public, loopback, multicast, unspecified, and broadcast
   targets before the packet engine is called.
4. **Installer removed Windows trust metadata.** The recursive
   `Zone.Identifier` deletion routine was removed. The installer no longer
   attempts to bypass Mark-of-the-Web or SmartScreen trust decisions.
5. **CI consumed the loose requirements file.** Hosted and hardware test jobs
   now install the hashed lock with `--require-hashes`.
6. **Mutable GitHub Action references.** Workflow actions are pinned to reviewed
   full commit SHAs. Hosted jobs use current Node 24-capable action releases;
   the self-hosted hardware job remains on a pinned Node 20-compatible
   `setup-python` until its runner is certified at version 2.327.1 or newer.
7. **No dependency-change gate.** A pinned dependency-review workflow now fails
   on newly introduced moderate-or-higher runtime vulnerabilities.
8. **No automated update cadence.** Dependabot now reviews Python and GitHub
   Actions dependencies weekly.
9. **No privileged-binary provenance guard.** SHA-256, size, source, version,
   and Authenticode observations for WinDivert and clumsy artifacts are recorded
   in `packaging/binary-provenance.json`; tests fail if bytes drift.
10. **No public security-reporting contract.** `SECURITY.md` now defines private
    reporting guidance, supported versions, redaction expectations, and scope.

## Phase-two hardening completed

11. **Explicit operation safety policy.** Active targets must fall inside
    configured owned local CIDRs. Public CIDRs cannot be configured, and the
    elevated helper independently rejects public disruption and firewall-block
    requests.
12. **Hard automatic stop deadlines.** Every controller-started operation gets
    a daemon-backed deadline, defaults to 300 seconds, and cannot exceed the
    3600-second hard ceiling. Re-arming a target invalidates its previous timer.
13. **True dry-run mode.** GUI settings and CLI expose dry-run. It loads no
    packet engine, scheduler, plugin loader, auto-scan worker, persisted rules,
    or active network service. It validates scope and parameters and emits a
    redacted audit event only.
14. **Fail-visible engine startup.** A false or exceptional packet-engine
    initialization now aborts controller startup and runs rollback instead of
    presenting a partially started application.
15. **Bounded persisted automation.** Scheduled rules and macro steps are
    clamped to one hour, repeat intervals to one day, macros to 100 steps and
    100 cycles, and the scheduler now uses an event-driven shutdown.
16. **Safe runtime policy changes.** Changing CIDRs, dry-run state, or maximum
    duration validates before persistence, stops active operations when policy
    changes, and rolls back invalid settings.
17. **In-process plugin capability reduction.** Raw-packet, process-spawn, and
    user-data-write capabilities are refused in production until plugins move
    to an OS-isolated process. `ctypes` imports/native audit events are also
    denied as best-effort defense in depth.
18. **Security ownership.** CODEOWNERS now requires owner review for CI,
    core security, helper, plugin, packaging, signing, and release surfaces.
19. **Fail-closed release preflight.** Version synchronization, immutable Action
    references, hashed dependencies, binary provenance, security-control files,
    and required release artifacts are checked before release.
20. **Release metadata is first-class.** Variant builds now use the hashed
    runtime lock, pin PyInstaller, generate SBOM and VEX documents, copy binary
    provenance, and the release driver uploads all nine required artifacts.

## Phase-three hardening completed

21. **Crash-safe network recovery journal.** Active packet or firewall work
    creates an atomic marker under the user-local recovery directory. It stores
    no target IP, MAC, hostname, or account data.
22. **Fail-closed startup restoration.** A stale or corrupt marker causes packet
    operations and DupeZ firewall rules to be cleared before schedulers,
    plugins, or scanners start. Incomplete restoration aborts startup and keeps
    the marker for the next recovery attempt.
23. **Clean shutdown restoration.** Normal shutdown now stops all active packet
    work, removes DupeZ firewall rules, clears operation deadlines, and only
    removes the recovery marker after both cleanup paths succeed.
24. **Helper crash cleanup.** The elevated helper now stops all device engines
    and clears helper-owned firewall rules before exiting.
25. **Parent PID reuse protection.** The helper watcher binds to both parent PID
    and process creation time, so a recycled PID cannot keep a stale elevated
    helper alive.
26. **Recovery diagnostics.** Diagnostics reports a pending or corrupt network
    recovery marker and explains the fail-closed startup recovery path.
27. **CodeQL.** Python security-extended CodeQL analysis now runs on pushes,
    pull requests, and a weekly schedule using an immutable action commit.
28. **Endpoint protection remains enabled.** Diagnostics and build comments no
    longer recommend broad Microsoft Defender/antivirus exclusions. Locked
    artifacts are handled through clean directories, rename/retry behavior,
    signatures, and hashes.

## Phase-four hardening completed

29. **Exact IP-forwarding crash restoration.** The recovery journal now records
    the original forwarding state without network identifiers. ARP-spoof and
    LAN-cut paths record state before changing it, clear their reason after
    successful restoration, and preserve unrelated pending recovery reasons.
30. **Cross-path forwarding recovery.** Controller startup restores the exact
    prior forwarding value before clearing a stale journal. A failed forwarding
    restore keeps the journal and aborts startup.
31. **Hard helper lifetime binding.** Elevated helpers are assigned to a Windows
    Job object configured with `KILL_ON_JOB_CLOSE`. A GUI crash therefore closes
    the job handle and terminates the helper at the OS boundary.
32. **Layered helper supervision.** PID-plus-creation-time watching remains as a
    fallback when a scheduled-task or host policy prevents Job assignment.
33. **Review-only secret-store ACL recovery.** The CLI now emits redacted
    inspection, ownership, and ACL commands through
    `recovery secret-store-repair-plan`; it never changes permissions
    automatically and warns operators to preserve encrypted files first.
34. **Host-safe test isolation.** Tests redirect the operation journal into
    per-test temporary paths, preventing fault-injection runs from touching the
    real user's recovery state.

## Phase-five product trust and market hardening completed

35. **Versioned operator acknowledgement.** First GUI launch now requires an
    explicit owned-or-authorized-network acknowledgement before the splash,
    controller, plugins, scanners, or packet engine initialize. The atomic
    per-user record contains only policy version and timestamp.
36. **CLI authorization controls.** `safety status`, `safety acknowledge`, and
    review-only `safety reset` expose the same policy without Administrator
    access. Active CLI disruption refuses to start without acknowledgement;
    dry-run remains available for safe validation.
37. **Accessibility baseline.** Icon-only navigation, window controls, status
    indicators, renderer state, collapsible help sections, and the first-run
    dialog now expose accessible names or descriptions.
38. **Defensive market positioning.** The competitive audit now benchmarks
    Clumsy, NetCut, Pktmon, and WinDivert around usability, diagnostics, scope,
    recovery, release trust, and supportability. It explicitly rejects
    deauthentication, DHCP abuse, forensic weakening, server-integrity bypass, and
    unauthorized public-server use as product goals.
39. **Roadmap and README correction.** Current product documentation now leads
    with authorized lab testing, DayZ connection diagnostics, dry-run,
    deadlines, and recovery. Legacy v6 proposals are marked archived where
    they conflict with the current safety boundary.

## Phase-six explainable Network Health completed

40. **Unified health snapshot.** A stable `dupez.network-health.v1` report now
    combines diagnostic severity, aggregate adapter readiness, default-route
    type, safety-policy state, acknowledgement, pending recovery, and
    prioritized recommendations.
41. **Windows-native capability detection.** Network Health reports whether the
    in-box Microsoft Pktmon and its PCAPNG path are available without starting
    a capture or changing host state.
42. **Privacy-preserving network inventory.** Health output excludes adapter
    display names, MAC addresses, raw IP addresses, and packet payloads. It
    includes only aggregate adapter counts/counters and masked route data.
43. **GUI and automation parity.** `Tools → Network Health` (`Ctrl+F2`) exposes
    the summary in the desktop app, while `python -m app.cli health --json`
    provides the same schema for support automation without Administrator
    privileges.
44. **Evidence-driven recommendations.** Failures and warnings are converted
    into a bounded, deduplicated next-action list instead of forcing operators
    to interpret raw component state.

## Phase-seven bounded Pktmon diagnostics completed

45. **Review-first capture planning.** `pktmon plan` validates a required
    TCP/UDP port filter, optional IP literal, destination, duration, privacy
    impact, and output names without Administrator access or state changes.
46. **Hard capture limits.** Applied captures are restricted to NIC
    components, 30 seconds, 32 MB circular logging, and 64 captured bytes per
    packet. Hostnames, unspecified/multicast filters, unbounded files, and
    overwrites are refused.
47. **Two-step sensitive-data consent.** Actual collection requires both
    `--apply` and `--accept-sensitive-capture`, plus Administrator rights.
    Plans and results state that network identifiers and a packet prefix may be
    present and that files must be reviewed before sharing.
48. **Global-state protection.** DupeZ checks existing Pktmon filters and
    refuses to continue if any are configured, because Pktmon can only remove
    all filters globally. Filters and capture state are cleaned in a `finally`
    path before ETL-to-PCAPNG conversion.
49. **No automatic capture or upload.** Pktmon is never started during launch,
    health checks, or diagnostics. Capture output remains local and is never
    attached to support bundles or uploaded automatically.
50. **Capture privacy lifecycle.** Default ETL, PCAPNG, and PCAP artifacts are
    now inventoried by `privacy scan` and supported by dry-run, quarantine, and
    explicit delete workflows.

## Phase-eight reproducibility and active-state transparency completed

51. **Visible automatic-stop countdowns.** Active device rows now display the
    remaining safety deadline rather than only a generic active badge. Missing
    deadline state is shown explicitly instead of silently implying safety.
52. **Privacy-preserving operation API.** Controller snapshots expose masked
    target scope, sorted methods, elapsed time, absolute/remaining deadline,
    process state, and automatic-stop state. Raw parameter values are replaced
    by stable canonical SHA-256 fingerprints.
53. **Machine-readable status parity.** `status --json` exports the operation
    snapshot with redacted engine/stat data so automation can verify that
    every active operation has a bounded lifetime.
54. **Deterministic scenario reports.** CLI and GUI export normalized JSON
    reports with stable content IDs, UTC timestamps, explicit methodology,
    operator observations, and RFC 2330/2679/2680/5481 metric references.
55. **Atomic and idempotent report output.** Reports are fsync-and-replace
    written, never overwrite a different report, and reuse an existing file
    when the normalized report ID matches.
56. **Report privacy boundary.** Reports exclude raw targets, packet payloads,
    and parameter values. IP/MAC identifiers in operator notes are masked and
    free-text review is explicitly required before sharing.

## Phase-nine installed-runtime storage separation completed

57. **Per-user installed storage.** Frozen/installed builds now resolve
    mutable data and configuration beneath `%LOCALAPPDATA%\DupeZ`; source
    checkouts retain explicit repository-local development paths.
58. **Complete mutable-path consolidation.** Settings, HMAC sidecars, device
    caches, histories, scheduler state, episodes, profiles, trained models,
    webhook allowlists, logs, captures, reports, and crash dumps use canonical
    runtime roots rather than writing beside installed binaries.
59. **Verified copy-only migration.** Recognized legacy files are copied
    through a temporary path, SHA-256 verified, and atomically promoted.
    Existing destinations win, conflicts are recorded, sources are never
    deleted, and failed migrations remain retryable.
60. **Settings integrity path unification.** `AppState` now uses the canonical
    HMAC-protected configuration loader/writer for production settings instead
    of bypassing the sidecar integrity policy with a second plain-JSON path.
61. **Location-independent backup format.** Backups preserve stable logical
    `app/data` and `app/config` names while installed restores map them to
    per-user roots. Restore writes are temporary, fsynced, hash-verified, and
    atomically replaced.
62. **Storage health diagnostics.** Diagnostics detects mutable state beneath
    the binary directory, migration copy failures, and preserved conflicts.
    It explicitly instructs operators not to delete legacy files before
    review.
63. **Unified privacy lifecycle.** Privacy inventory and quarantine now cover
    runtime data, packet captures, rotating logs, and scrubbed fatal-crash
    reports across their canonical roots.

## Phase-ten retention and support lifecycle completed

64. **Conservative age-based retention.** `privacy retention` now builds a
    dry-run plan across packet captures, support bundles, reports, logs, crash
    reports, audit metadata, episodes, diagnostics probes, scheduler state, and
    device caches. Account/profile data remains opt-in.
65. **Safe retention enforcement.** Applied retention reuses the privacy scrub
    path, quarantines by default, supports explicit delete, and accepts
    per-category `CATEGORY=DAYS` overrides without broad filesystem traversal.
66. **Support-bundle lifecycle visibility.** Redacted support bundles now
    include retention rule metadata and eligible file counts/bytes, so support
    can spot unbounded local artifact growth without receiving raw logs,
    captures, account contents, IPs, MACs, or user-specific paths.
67. **Report/support artifact inventory.** Scenario reports and support-bundle
    JSON files are now included in privacy inventory and can be managed by
    retention or scrub workflows.
68. **Backup and quarantine lifecycle.** Managed backup archives now default to
    the per-user DupeZ backup root, appear in privacy inventory, and participate
    in retention. Old `privacy-quarantine-*` directories are inventoried with
    recursive size accounting and can be quarantined again or explicitly
    deleted by retention policy.
69. **Storage observability.** `storage status` exposes a read-only,
    privacy-preserving map of managed runtime roots, installation/source mode,
    migration marker health, and legacy-file candidate counts. JSON output and
    support bundles redact user-specific local paths.
70. **Support bundle storage context.** Redacted support bundles now include
    storage/migration status alongside diagnostics, secret-store health,
    retention, and privacy inventory metadata, allowing support to spot
    installation-tree writes or incomplete migrations without collecting raw
    files.
71. **Performance smoke budgets.** `performance smoke` measures local,
    no-engine supportability paths against explicit p95 budgets for storage
    status, retention planning, and scenario report creation. Full support
    bundle creation can be included explicitly for slower diagnostic runs.
72. **Machine-readable performance output.** The performance smoke command runs
    without Administrator privileges and emits stable JSON so CI/support can
    detect regressions before operators experience sluggish diagnostics.
73. **Active DayZ content sanitation.** The shipped DayZ tips, game profile,
    latency configuration, and legacy-named DayZ configuration file now
    describe passive diagnostics, authorized local-lab impairment scenarios,
    privacy-preserving reporting, and private-server troubleshooting instead
    of game-state manipulation, bypass-risk tuning, or success-rate claims.
74. **Controller-script safety repositioning.** Built-in GPC templates now
    provide accessibility, comfort, and private diagnostic marker workflows
    only. Legacy exploit-oriented template names are removed and guarded by a
    regression test.
75. **Active-content guardrail.** A new test blocks reintroduction of known
    exploit/evasion phrases in active DayZ config and GPC generator content.

## Remaining priority roadmap

### P0 - Operator and target safety

- Completed: first-run acknowledgement for owned or explicitly authorized
  local test networks, with a versioned privacy-preserving per-user record and
  CLI status/acknowledgement controls.
- Completed: active DayZ guidance/config and GPC templates have been
  repositioned around diagnostics, accessibility, and authorized local-lab
  testing.
- Add an optional session-specific device allowlist on top of the persistent
  local CIDR policy.
- Add adapter-specific forwarding state if future versions modify more than the
  active default interface.

### P0 - Release and privileged binary integrity

- Rebuild `clumsy.exe` reproducibly from the bundled source in CI and compare it
  with the shipped hash, or remove the fallback binary.
- Authenticode-sign all first-party executables and DLLs. Keep the signed
  WinDivert driver provenance and timestamp evidence with each release.
- Add artifact attestations for installers, SBOM, VEX, update manifest, and
  binary-provenance manifest.
- Produce attestations from the workflow that actually builds the artifacts.
  Do not attach misleading build-provenance attestations to binaries merely
  downloaded by a later workflow.
- Fail release preflight when signing is absent, timestamping fails, the VEX is
  still entirely `under_investigation`, or binary provenance drifts.

### P1 - Plugin isolation

- Continue treating the Python audit hook as telemetry and best-effort policy,
  not a security sandbox. CPython explicitly warns that Python-added audit hooks
  are bypassable by malicious code.
- Move untrusted plugins to a low-integrity/AppContainer-style brokered process
  with explicit IPC capabilities, resource limits, no inherited handles, and
  separate writable directories.
- Add activation review, capability diffing on upgrade, violation quarantine,
  and a one-click disable-all recovery path.

### P1 - Architecture and reliability

- Rename or archive the consent-gated `app/offsec` local self-test package so
  active source names match the defensive product position.
- Split the five 1,400-1,800 line orchestration/UI modules along engine,
  policy, process, state-adapter, and view boundaries.
- Replace remaining import-time managers with explicit providers and typed
  protocols.
- Add crash-journaled network-state restoration and fault-injection tests for
  every cleanup stage.
- Make engine initialization fail visibly rather than allowing the controller to
  appear started after initialization returns false.

### P1 - Data and privacy

- Completed: mutable installed-runtime settings and user data now live under
  `%LOCALAPPDATA%\DupeZ` with verified copy-only legacy migration.
- Completed: conservative retention planning/enforcement for packet captures,
  support bundles, reports, logs, crash reports, audit metadata, episodes,
  diagnostics probes, scheduler state, device caches, managed backup archives,
  and old privacy-quarantine directories.
- Add an in-app inventory and export warning that classifies IP, MAC, account,
  and free-text note exposure.

### P2 - CI and quality

- Add CodeQL analysis for GitHub Actions workflow source when repository
  licensing and GitHub support allow it.
- Add a dedicated packaging smoke build and installer compile check.
- Add coverage thresholds for validation, updater, helper authentication,
  cleanup, and plugin lifecycle code.
- Test Python 3.13 once all binary dependencies support it; retire unsupported
  Python versions explicitly.
- Add performance budgets for scanning, GUI startup, map-host startup, packet
  hot paths, and shutdown latency.

## Primary-source research used

- GitHub secure-use guidance: least-privilege workflow tokens, immutable
  full-length action SHAs, caution with self-hosted runners, CODEOWNERS, and
  supply-chain scanning.
- GitHub dependency-review documentation: block vulnerable dependency changes
  before merge.
- CPython `sys.addaudithook` documentation: Python audit hooks are not a
  malicious-code sandbox.
- Microsoft AppContainer guidance: isolate file, registry, network, process,
  credential, device, and window access by least privilege.
- OWASP Logging Cheat Sheet: protect local log storage, avoid unnecessary
  sensitive data, verify logging behavior, and dispose of logs intentionally.
- Microsoft Windows app-data guidance: store mutable application data under
  user-local application-data locations rather than installation directories.
- NIST Privacy Framework: minimize, manage, and communicate data processing
  risks over the data lifecycle.
- Microsoft Job Object guidance: group child processes, enforce resource/time
  limits, and terminate process trees with kill-on-job-close.
- Microsoft driver-signing requirements: SHA-2 signing and signed driver
  submission requirements.
- Current official action release notes for Node 24 runner compatibility.
