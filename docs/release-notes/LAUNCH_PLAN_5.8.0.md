# DupeZ v5.8.0 release and launch plan

Status checked: 2026-10-25. Disposition: **SOURCE CANDIDATE / PUBLIC RELEASE BLOCKED**.

This is an execution plan, not a release approval. No public launch date is
committed. Do not promote the old files in `dist`, the prior private engineering
snapshot, or a passing source-only preflight into a release candidate.

## Current decision map

| Gate | Verified state | Owner / next action |
| --- | --- | --- |
| Source changes | October 25 build checkpoint `bca1e44` and separate source/candidate evidence are tracked through the existing PR 84 branch | PR head and its checks are authoritative for source publication; neither a branch push nor this plan authorizes release |
| Hosted CI | October 25 verification of prior pushed head `6fa81f4` found all 14 checks blocked before execution by the account billing lock | Owner resolves the account restriction privately; obtain checks on the newest exact head without bypass |
| Main governance | Active `main-release-integrity` ruleset, no bypass actors, PR and resolved threads required, 14 strict checks | Preserve controls; reverify before merge/publication |
| Production environment | `production-release` permits only branch `main`; readiness variable is set | Preserve controls; no independent reviewer is claimed for this solo-maintainer setup |
| Distribution terms | GPL-3.0-only selected by owner; full license and selection record prepared, contribution rights still unconfirmed; six decisions unresolved | Owner confirms rights and use context; complete dependency/notices/source-delivery evidence before recording approvals |
| Signing route | Owner selected the explicitly disclosed unsigned/manual-install route on October 7 | Preserve `-AllowUnsigned` through all phases; verify protected updater signing separately; never share private keys in chat |
| Dependency advisories | October 24 refresh updates Pillow, certifi, cryptography and test/bootstrap pip; updated runtime scan has zero active PyPI advisory records across 27 packages | Keep the generated locks and component inventory together; this scan does not cover native Qt/Chromium or the interpreter |
| Native runtime security | Browser/QML payload removed from both frozen builds; 128 native entries each from approved origins. Separate Qt 6.11.3 candidate passes widget/SVG/Schannel probes | Production builds still use Qt 6.11.2; finish candidate inventory, plugin parity, frozen/TLS validation and software OpenGL review |
| Source/rebuild evidence | All 33 upstream archives collected and independently bundle-verified; all four managed binaries match official release assets; earlier GPU application/LGPL Python-layer modification evidence retained | IUP source replacement date, exact native rebuild/replacement, public source delivery/retention and owner decisions remain unresolved |
| Full Clumsy integration | Standard-module wiring exists, but full observable behavior parity is not established | Complete the scoped control/lifecycle/effect evidence matrix below on both frozen variants |
| Disruption hotkeys | Opt-in configuration, Qt dispatch, owned lifecycle and F1 registration reporting implemented with mocked regression coverage | Exact-build background/tray, elevated-window and key-release checks remain required |
| Exact artifacts | Fresh isolated GPU/Compat at `bca1e44` pass offline checks. GPU maintenance and both v4 safety dry-run lifecycle profiles pass; Compat UAC was canceled before execution | Operator approves normal UAC to finish Compat. These are engineering artifacts; rebuild on protected main after all release gates |
| Launch operations | Copy and rollback checklist prepared below | Publish only after verified draft; then verify the public download and communicate |

Live evidence was read from [PR 84](https://github.com/GrihmLord/DupeZ/pull/84),
the repository ruleset/environment APIs, and the
[source-release check](https://github.com/GrihmLord/DupeZ/actions/runs/33845703840).
The account-lock annotation explains why the September job did not run; it is not
evidence that local tests failed or that billing remains blocked. The launch-attempt
refresh verified successful October 6–7 hosted runs, including
[CodeQL on current main](https://github.com/GrihmLord/DupeZ/actions/runs/37662373073).
Those runs do not validate this PR 84 source refresh. No payment,
downgrade or account change was made by this work.

## October 25 containment, source mapping and candidate runtime

- Fixed the real clean-build failure caused by browser designer files collected
  as data. Both final archives reject embedded browser/QML payloads and contain
  identical inventories of 128 native entries. Each executable is about 69 MB.
- Stable checkpoint tests: **3,367 passed, 10 expected skips, 58.40% app line
  coverage**. Exact-source ZIP and notice verification pass. GPU imports,
  Schannel-only TLS selection, and normal/low-resource dashboard lifecycles pass.
- **Compat runtime remains untested:** Windows canceled the normal UAC request
  before the test helper started. No bypass or repeated elevation was attempted.
- **33 source archives** are retained and independently bundle-verified. All
  four managed binaries match official packages. IUP's later source replacement
  and independent native rebuild inputs remain explicit gaps.
- An isolated official Qt 6.11.3 candidate passes retained-module/widget/SVG/
  Schannel probes. Its hardened preparer passes **51 tests**, and recipient
  preparation matches all **933 wheel member payloads**. Production locks and
  licensing approvals are unchanged; full candidate integration remains open.

Evidence: [build/runtime audit](../audits/NATIVE_CONTAINMENT_2026-10-25.md),
[measured results](../../packaging/license-evidence/native-containment-2026-10-25.json),
[source mapping](../legal/NATIVE_SOURCE_MAPPING_2026-10-25.md),
[Qt candidate](../audits/QT_NATIVE_REVIEW_2026-10-25.md).

## October 24 clean-build and recipient evidence (historical checkpoint)

- Code checkpoint **`1db32d750ee1a1b23733ff38f6b53fdad8957d7f`** was archived
  and independently passed the exact-commit source ZIP gate. The isolated route
  built clean GPU/Compat and a separately modified GPU without Git metadata,
  production signing keys, installer creation, or canonical output changes.
- Fixed a measured native packaging leak: the diagnostic baseline's raw Analysis
  inventory contained 48 DLLs from unrelated Poppler/libheif directories. The
  corrected final CArchives contain **259 native binaries** each, all byte-bound
  to the locked venv, verified PSF runtime, or exact managed input. Native
  inventories match across the clean and modified artifacts; no ambient origin
  was admitted. The diagnostic executable was never launched.
- Clean and modified GPU passed standard-user imports and the real native TLS
  probe with **Schannel as the only available/active backend**, exit 0. The
  modified build reported the application marker and actual zeroconf LGPL
  Python-function result. This is not native Qt/Chromium/Cython replacement,
  bit-for-bit reproducibility, or full lifecycle/hardware evidence.
- Final exact-checkpoint suite: **3,270 passed, 10 skipped, 58.28% app coverage,
  238.47 seconds**. Six skips need opt-in hardware and four need symlink rights.
  Source/frozen preflights and staged hooks pass. No Compat administrator runtime,
  renderer, packet manipulation, installer, or game workflow was exercised.
- **32 upstream source archives** (1,733,386,826 compressed bytes) were retained,
  hash-checked and safely inspected; deterministic bundle and independent bundle
  verification passed with identical receipts. All 33 inventory components are
  represented; IUP remains unresolved. Exact Qt/Chromium wheel patches/build
  mapping, native replacements, public delivery/retention and owner rights still
  prevent a complete corresponding-source claim.
- Exact-checkpoint notices generated and verified: **27 runtime components / 76
  notice documents**. The six distribution decisions and complete-source gate
  remain blocked; no approvals were manufactured. No binaries, tag or release
  were published by these local observations.

Evidence: [native audit](../audits/NATIVE_CONTAINMENT_2026-10-24.md),
[recipient hashes/results](../../packaging/license-evidence/recipient-rebuild-2026-10-24.json),
[source-input recipe](../legal/CORRESPONDING_SOURCE_INPUTS_V5.8.0.md),
[source receipt](../../packaging/license-evidence/source-input-collection-2026-10-24.json).
These observations belong to their recorded build checkpoint, not automatically
to later documentation commits or future official release binaries. Hosted CI
is still a separate billing-blocked requirement; see the
[last checked run](https://github.com/GrihmLord/DupeZ/actions/runs/40074213766).

## Earlier October 24 native-runtime follow-through

- Active release scripts, workflows and target metadata now require CPython
  **3.13.17 x64**. A workspace-isolated official Python NuGet package was verified
  against its catalog SHA-512 and valid Python Software Foundation Authenticode
  signature; no system Python installation was changed. It reports OpenSSL
  **3.5.9**, replacing the older interpreter's OpenSSL 3.0.21.
- The generated runtime lock and license inventory now include native
  **Qt 6.11.2 / QtWebEngine 6.11.2** (bindings remain 6.11.0). Runtime inspection
  reports Chromium security backports through **151.0.7922.71**. These are the
  latest Riverbank wheels checked today, not a claim that 6.11.3 fixes are present.
- A new fail-closed browser admission policy checks the actual Windows token,
  sandbox/debug configuration, browser arguments and native runtime versions.
  Elevated, unverifiable, unsandboxed or unpatched contexts cannot construct a
  browser view or start a child map. Current Qt 6.11.2 is intentionally denied
  in both variants; the UI displays an approved URL for manual opening in a
  normal non-administrator browser, without invoking an elevated URL handler.
- For a future admitted runtime, navigation and network requests are restricted
  to exact reviewed HTTPS hosts. Unknown schemes/origins, popups, downloads,
  file selection, permissions and certificate overrides are denied. An ephemeral
  profile avoids inherited browser state; injected application scripts require
  a currently approved origin. Child IPC, retries and lazy-loading paths share
  the same checks. Admitted runtimes still require exact frozen validation.
- Review also closed two startup-policy gaps: an empty sandbox-disable variable
  is denied because Qt treats its presence as disabling the sandbox, and flags
  after `--webEngineArgs` use the same reviewed allowlist as environment flags.
  Denial retires existing views, retains failed parent cleanup for retry, and
  suppresses late ready callbacks rather than treating hidden views as stopped.
- The owner selected **GPL-3.0-only with corresponding source**. The complete
  license and dated selection record are prepared. No contribution-rights,
  commercial-entitlement or delivery approval was invented. The
  [owner-action checklist](BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md#owner-action-checklist-2026-10-24)
  gives exact billing steps and maps all six licensing decisions to evidence.
- Inno Setup 6.7.1 permits commercial use under its published grant; buying a
  commercial license is not inherently required. Record the actual use context
  and chosen basis. Existing source archives/upstream links alone do not prove
  complete corresponding-source or usable recipient replacement/rebuild delivery.
- Frozen GPU/Compat, installer, source/relink delivery and manual/hardware gates
  remain open. No release/tag or binary publication is authorized by these changes.

Primary references: [Python 3.13.17](https://www.python.org/downloads/release/python-31317/),
[Qt native advisories](https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products),
[QtWebEngine patch levels](https://wiki.qt.io/QtWebEngine/ChromiumVersions),
[GitHub billing-lock recovery](https://docs.github.com/en/billing/how-tos/troubleshooting/locked-account),
[Inno licensing FAQ](https://jrsoftware.org/isorder.php).

### Native-runtime checkpoint verification

- Final Windows CPython 3.13.17 x64 full suite: **2,947 passed, 10 skipped in
  157.24 seconds; 57.86% app coverage** (40% gate). Six skips are opt-in hardware
  cases and four require unavailable symlink privileges. No renderer, frozen
  lifecycle or hardware pass is inferred from mocked security-policy tests.
- Runtime/test hash-required installation, `pip check`, all four lock contracts,
  source preflight, Ruff, AST parsing of 432 Python files, changed PowerShell
  parsing, whitespace checks and all applicable staged commit hooks pass.
- Runtime inspection confirms Python 3.13.17, OpenSSL 3.5.9, Qt/WebEngine 6.11.2
  and Chromium security 151.0.7922.71. Browser admission correctly denies the
  installed Qt build. The updated 27-package PyPI scan has zero active records;
  it is not a native-runtime or GitHub default-branch vulnerability clearance.
- Local evidence is under `build/native-security-20261024/`, including
  `pytest-reviewed.xml`, `coverage-reviewed.json`, and `vulnerability-review.json`.
  Generated environments/reports and the existing local PDF are not committed.
- Distribution-license preflight still fails on six unresolved decisions.
  GPL selection and the keyless recipient-build recipe are recorded, but rights,
  delivered corresponding source and recipient replacement remain unverified.
  No binary build, tag, merge or release publication was performed.

## October 24 source and security refresh

This earlier checkpoint describes the candidate before the native-runtime
follow-through above. Its old interpreter and map findings are retained as
history, not the current implementation state.

- The owner requested a source push and new release/tags. Source publication to
  the existing development branch is separate from binary-release approval;
  unresolved owner, native-security and exact-artifact gates still block a
  public release/tag. No existing `dist` artifacts are promoted.
- A fresh version-specific PyPI review found 39 active advisory records against
  the old runtime lock: 37 for Pillow and two certifi aliases. This is not a count
  of unique CVEs. The regenerated runtime lock updates Pillow to 13.0.0, certifi
  to 2026.10.23 and cryptography to 50.0.2; the earlier urllib3 2.8.0 fix remains.
  Component versions and license metadata remain aligned. The refreshed scan
  reports zero active records for all 27 locked runtime packages.
- Pillow's October release repairs image-decoder/encoder memory-safety and
  resource-exhaustion issues. Certifi removes a compromised emSign chain;
  cryptography's Windows wheels update bundled OpenSSL to 4.0.3.
  [Pillow release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html),
  [certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2),
  [cryptography changelog](https://cryptography.io/en/latest/changelog/).
- Test and CI/bootstrap pip pins move to 26.2.2, which updates its own vendored
  certifi trust store. Runtime certifi alone would not repair pip's bundled copy.
  [pip release notes](https://pip.pypa.io/en/stable/news/).
- Release finalization now honors `DUPEZ_BOOTSTRAP_PYTHON`, validates the exact
  canonical 3.13.14 x64 interpreter and forwards it to the builder. Invalid
  overrides and paths inside disposable `.release-venv` fail closed. This fixes
  the October 7 interpreter-selection mismatch without relaxing version gates.
- Invalid hotkey settings no longer hide an outstanding hook-cleanup failure.
  Stale chord labels clear while failed removals remain disarmed, owned and
  retryable; a successful retry clears the error. No live packet manipulation
  or game-character cloning was exercised or established.
- Remaining native-security work: upstream Python 3.13.17 includes further
  security updates, and Qt lists HTTP/2 and JSON-parser fixes in 6.11.3.
  QtWebEngine 6.11.2 also has newer Chromium security backports than 6.11.0.
  The current pins were not silently declared safe or migrated without frozen
  validation. A zero PyPI finding count cannot resolve these native risks.
  [Python 3.13.17](https://www.python.org/downloads/release/python-31317/),
  [Qt advisories](https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products),
  [QtWebEngine security versions](https://wiki.qt.io/QtWebEngine/ChromiumVersions).
- Native reachability review found a concrete surface needing further work:
  the in-process map loads remote content with JavaScript enabled; its request
  interceptor is an advertising denylist, not an origin allowlist. Initial
  iZurvive URL validation does not constrain redirects, clicks or subresources.
  Compat's administrator manifest and disabled Chromium sandbox make this an
  explicit release risk. Add and test shared navigation/popup/resource policy,
  assess a sandboxed non-elevated or external-browser Compat route, and verify
  actual sandbox/token state on both frozen variants. Absence of direct app
  calls to Qt's HTTP/2 or JSON parser is not a native non-exploitability finding.
- Local before/after package-review evidence is retained under
  `build/release-research-20261024`. These working-tree checks do not substitute
  for exact-commit CI, frozen GPU/Compat, installer, hardware or updater evidence.

### October 24 verification

- Full Windows CPython 3.13.14 x64 suite against the updated hash-pinned graph:
  **2,734 passed, 10 skipped in 284.07 seconds; 57.43% app coverage** (40% gate).
  Six skips require opt-in hardware testing; four require unavailable symlink
  privileges. None is represented as a hardware or frozen-build pass.
- Hash-required runtime/test install and `pip check`, all four lock contracts,
  exact-version component inventory and upgraded-package license metadata pass.
- Source preflight, Ruff, AST parsing of 429 Python files, finalizer PowerShell
  parsing, whitespace checks and the Windows release-progress I/O contract pass.
- Read-only changed-file secret review: 70 text files, zero new findings; the
  existing baseline is unchanged. All configured staged pre-commit hooks pass.
- Full-suite evidence: `build/release-research-20261024/pytest.xml` and
  `build/release-research-20261024/coverage.json`. These are local working-tree
  results; consult PR 84 for the subsequently pushed exact head and hosted checks.
- Distribution preflight still fails with six unresolved owner decisions.
  No binary rebuild, tag or release publication was performed by this refresh.

### October 7 build/test/GitHub launch attempt

- The owner requested build, test and GitHub publication and explicitly selected
  the unsigned/manual-install distribution route. Indifference to licensing is
  not recorded as approval of any specific project terms or third-party entitlement.
- Source preflight passes; the actual distribution-license preflight exits 1
  with all six owner decisions unresolved. No license gate was disabled.
- Fresh supported-Python release-pipeline regression run: **170 passed in 21.89
  seconds**. Evidence: `build/github-launch-attempt-20261007/release-tests.xml`.
  The latest complete source suite remains the 2,713-pass run recorded below.
- `DUPEZ_SIGN_PRIVKEY` is configured and its referenced file exists. Only file
  presence was checked; private contents were not read and the signing key has
  not yet been matched to the pinned public key for this release.
- The canonical finalizer uses `.venv`, currently Python 3.11.9, while release
  tooling requires Windows x64 Python 3.13.14. The supported test interpreter is
  separate; passing its tests does not repair the build bootstrap automatically.
- `packaging/build_variants.bat` recreates its environment, terminates named app
  processes and deletes canonical `dist` outputs. It was not run as a probe.
  After resolving prerequisites, use an isolated real clone and preserve existing
  artifacts; canonical provenance does not accept a managed-worktree `.git` file.
- PR 84 remains draft at `f455f56257c8bc4fb9c7045efcb2f71d57d6a25c`; all 14 checks
  for that head remain failed/stale. Protected `main` is
  `77fb1d8883c1942be163ff5f67c9794d38591d0f`. No bypass or environment-rule change
  was made. Recent successes on other commits are not release approval.
- No new binaries were built, uploaded or published during this attempt. No
  source commit, push, merge, tag, draft mutation or workflow dispatch occurred.

## October 7 functionality and dependency review

The resumed review preserves the earlier backup, support-export, AI request
isolation, updater handoff, and release-progress work. It additionally repairs:

- Headerless account CSV imports dropping rows after the first, including empty
  columns, multiple delimiters, BOM/leading blank lines and quoted multiline data.
  Malformed quoting, invalid UTF-8 and duplicate mapped headers reject the batch
  before persistence. Individual invalid/duplicate account rows remain counted skips.
- CSV/XLSX exports now stage complete content before replacing an existing file;
  failed writes leave the previous export intact. Missing XLSX support cannot
  produce a success message. Subset exports do not temporarily mutate the view.
- Manual account edits reject duplicate names; quick-switch/clear actions and
  their status messages reflect whether persistence actually succeeded.
- Diagnostic write probes use their own exclusive temporary file. Migration
  markers share schema/type validation with storage diagnostics; malformed or
  failed markers cannot crash reporting or silently suppress a migration retry.
- Copy-only migration uses unique stages and no-overwrite publication, preserving
  a destination created by a concurrent writer. Originals remain untouched.
- Dashboard shutdown attempts independent cleanup even if another timer, tray
  operation or service fails; an unconfirmed cleanup still vetoes installer launch.

The dependency scan was repeated because the September evidence was stale.
Upstream urllib3 2.8.0 fixes HTTPS-proxy TLS policy isolation, unbounded streamed
chunk-size buffering and a Deflate streaming loop. The source floor, generated
runtime lock and exact-version component inventory were updated together; the
other 26 runtime versions were unchanged. [Upstream release notes](https://github.com/urllib3/urllib3/releases/tag/2.8.0).

The Windows CPython 3.13.14 environment passed hash-required wheel installability
and `pip check`; installed urllib3 2.8.0 reports MIT license metadata. Local
before/after advisory evidence is retained under `build/launch-research-20261007`.
Zero listed PyPI advisories is not a claim that all dependencies, native binaries
or application behavior are vulnerability-free. Old release artifacts and
attestations do not cover the updated graph.

### Earlier October 7 baseline (before the hotkey/control pass)

- Full Windows Python 3.13.14 suite against the updated installed runtime graph:
  **2,506 passed, 10 skipped, 183.00 seconds; 55.64% app coverage** (40% gate).
  This is 96 more passing cases than the recovered September 5 suite.
- Skips: six explicitly opt-in hardware cases and four symlink-privilege cases.
  No skipped case is represented as a hardware, installer or filesystem-policy pass.
- Additional Python 3.11 focused account and diagnostics checks: 109 account cases
  and 141 diagnostics/storage/account-integration cases passed (overlapping suites,
  not additional unique coverage). The supported-release full run above used 3.13.
- Ruff, AST parsing of 419 tracked/new Python files, whitespace checks, all four
  runtime/test/build/hardware lock contracts, and exact-version component-inventory
  alignment passed. A read-only changed-file secret scan found zero new findings
  across 43 text files; the existing baseline was not modified.
- The Windows release-progress I/O contract passed, including second-process lock
  exclusion and preservation of the previous checkpoint on failed replacement.
- Saved full-suite JUnit and coverage JSON: `build/launch-research-20261007/pytest.xml`
  and `build/launch-research-20261007/coverage.json`. Advisory before/after reports
  are `vulnerability-review.json` and `vulnerability-review-patched.json` in that folder.

These were local working-tree results, not exact-commit release attestations.
At that October 7 snapshot, changes were uncommitted and unpublished. Real GPU/Compat frozen execution,
installer/UAC flows, hardware, external provider credentials and production
update delivery were not exercised. Migration remains copy-only per file, not a
multi-file transaction; abrupt termination can leave an owned temporary stage.

## Required Clumsy integration and hotkey workstream

Added October 7 following the operator's report that lag works but a DayZ
character-cloning outcome does not. The operator clarified that "duping" means
an in-game clone, **not** Clumsy's Duplicate packet module. These are separate
phenomena. No game-cloning cause or missing Clumsy option has been established.
Game exploitation, clone-generation sequences and unrestricted target/filter
bypasses are not product requirements or release success criteria. This workstream
is limited to authorized network-condition testing, reliable controls and cleanup.

### Research findings and limits

- The pinned binary is Kalirenegade 0.3.4, with source commit recorded in
  `packaging/binary-provenance.json`. All nine standard modules already have
  production routing. The fork advertises keybinds, presets, capture-layer and
  other controls; that does not establish DupeZ parity. [Upstream repository](https://github.com/kalirenegade-dev/clumsy),
  [pinned release](https://github.com/kalirenegade-dev/clumsy/releases/tag/0.3.4).
- Local source review finds the packet-copy count mapping consistent with the
  bundled implementation. Production installs the numeric notification adapter
  in `app/firewall/iup_edit_sync.py`; an older inactive character-wise setter
  must not be reported as the production cause without tracing adapter installation.
- `full_control_integration=True` describes control wiring, not measured packet
  effects. The existing full-controls hardware test uses zero duplication chance;
  it cannot prove packet duplication. Current runtime status explicitly lacks
  packet-effect verification. Do not convert startup/readback into an effect claim.
- Before the implementation pass, `app/main.py` bound bare `W` to `controller.toggle_lag()` without a target; that
  callback returns False without an IP and is a legacy firewall toggle, not a
  Clumsy action. It was separately owned from dashboard cleanup. Settings did not
  expose disruption keybinds. Listener startup could report success before actual
  registration, and listener replacement/stop could lose registration ownership.
  These source defects are addressed by the implementation below.
- The existing Stop All and Panic Stop menu shortcuts have window scope, not global
  scope. The new opt-in global hooks are separate registrations. Qt defaults also
  permit held-key repeats; application menu actions now disable repeats. The keyboard
  library dispatches asynchronously and documents limitations when other apps
  consume key events. [Qt shortcut behavior](https://doc.qt.io/qt-6/qaction.html#shortcutContext-prop),
  [keyboard API and limitations](https://github.com/boppreh/keyboard).
- Official DayZ notes document duplication-exploit fixes, but do not diagnose
  this report or establish that an old method works on a current build. Bohemia
  requests private reporting of sensitive duplication methods; use its current
  tracker and verify privacy before including sensitive evidence. No report was
  submitted. [Historical official fix](https://forums.dayz.com/topic/265911-stable-update-127/),
  [reporting guidance](https://feedback.bistudio.com/project/manage/2/),
  [current DayZ tracker](https://report.bistudio.com/projects/dayz).

### Implementation completed; manual acceptance still open

The October 7 source pass adds a **Settings → Hotkeys** tab. Global hooks are off
by default; Start has a separate opt-in. Defaults are Ctrl+Alt+F8 (Start),
Ctrl+Alt+F9 (Stop All) and Ctrl+Alt+X (Panic Stop). They are single chords, not
macros or timing sequences. Both the dialog and controller validate settings
before persistence. Validation rejects duplicates, known application conflicts,
bare keys and F12; it does not claim to detect every external application conflict.

All three global actions fire on **key release**. Start uses the normal selected-
target action on the Qt thread, is blocked during modal UI/shutdown/update handoff,
and cannot arm without both emergency hooks. A failed Start registration does
not disable working Stop/Panic hooks. Emergency actions cancel pending Start work.
The default local Panic shortcut is suspended only while its identical global
chord is armed; its menu action remains usable.

Registration is synchronous and reports actual success. Named hooks retain
ownership after failed removal, support safe rebind/rollback and reject stale
callbacks. F1 distinguishes window scope, configured chords, armed chords and
errors; an emergency chord retained after failed rebind is labelled explicitly.
Swapping chords still owned by another action is refused; use an unused interim
chord or disable/re-enable after confirmed cleanup. Startup's separate bare-W
no-op hook has been removed. Shutdown disarms queued work before cleanup.

Clumsy standard-module sliders now share the backend's numeric bounds across
engine-policy changes, preserving defaults. Duplicate is explicitly labelled
network-packet duplication and its count is labelled extra copies. Auto/Native
copy matches deterministic capability routing, with no fallback claim. No filter,
effect strength, disconnect timing, preset or packet-engine behavior changed.

The existing keyboard backend remains in use. Backend acceptance cannot prove
delivery while another app consumes keys, and this pass does not claim native
Windows hotkey exclusivity. Real focus/elevation, held-key behavior, frozen builds
and observed packet effects must still be verified before full-integration claims.

### Final source verification for this pass

- Full Windows Python 3.13.14 rerun after the final stop-button and callback-race
  fixes: **2,713 passed, 10 skipped in 178.30 seconds; 57.42% app coverage**.
  This is 207 more passing cases than the earlier October 7 baseline. The six
  opt-in hardware and four symlink-privilege skips remain unverified, not passes.
- Evidence: `build/hotkey-integration-20261007/pytest-final.xml` and
  `build/hotkey-integration-20261007/coverage-final.json`. Earlier files without
  the `-final` suffix represent an intermediate run, not the final patch.
- Mocked regressions cover registration failure, partial rollback, residual-hook
  ownership, independent emergency actions, conflict validation, local/global
  duplicate prevention, panel Stop-button wiring, Qt dispatch and stale callbacks
  both queued and accepted before an emergency action.
- Ruff and whitespace checks passed; AST parsing passed for 428 Python files.
  A read-only scan of 60 changed text files found zero new secret findings;
  the secret baseline was not modified.
- Read-only readiness still reports **blocked**: source preflight passes, six
  owner distribution checks fail, and 12 required inputs/evidence files are missing.
  That check did not query hosted CI or execute any existing binary.

These remain uncommitted source changes, not a rebuilt installer or a release
attestation. No live hooks, authorized-lab impairment or game sessions were run.

### Acceptance gates — source work does not close the manual gates

| Area | Required evidence |
| --- | --- |
| Pinned control parity | Compare every documented control, bound, direction, unit, preset and trigger mode to the pinned fork; verify both displayed values and callback synchronization |
| Routing and ownership | Standard effects stay on Clumsy; failures do not silently substitute Native. Preserve target policy, hard deadlines and one-process ownership |
| Observable lab behavior | Use benign authorized lab traffic and independent observations to distinguish configuration, capture and effect; label unavailable counters honestly; game outcomes are not packet-effect evidence |
| GPU/Compat parity | Validate in-process and authenticated-helper paths, normal/elevated windows, failed startup, cleanup refusal, diagnostic-window restoration and zero orphaned owned processes |
| Hotkey settings | Explicit opt-in start bindings, persisted validated configuration, conflict detection and visible registration errors; no bare-letter start default or implicit target selection |
| Hotkey execution | Route actions through the same validated controller/UI path on the Qt thread; reject stale queued callbacks; prevent held-key repeats and duplicate local/global firing |
| Emergency controls | Independently available global Stop All/Panic Stop with truthful scope/status, including background/tray focus; a failed start binding must not disable emergency cleanup |
| Registration lifecycle | One application owner, confirmed registration/unregistration, rollback after partial registration, safe rebind/replacement and shutdown-before-update ownership |
| Regression and manual tests | Mock registration failure/races, stale callbacks, conflicts, repeat keys and cleanup retry, then record exact-build keyboard/focus results without weakening any safety gate |

Evaluate Windows native registration as part of the hotkey design: it exposes
registration failure and a no-repeat flag; switching APIs is not itself proof of
correct ownership or UI dispatch. [Microsoft RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey).

The initial follow-up audit changed documentation only; the subsequent implementation
pass above changes source and mocked tests. No real global hooks, live impairment,
game-cloning automation or installer execution was used during verification.
Workstream gates remain open alongside the existing release blockers and require
exact-build completion evidence before calling integration full.

## Read-only preparation check

From the project's installed development/test environment:

```powershell
python scripts/release_readiness.py --version 5.8.0
python scripts/release_readiness.py --version 5.8.0 --json
```

An optional live check query requires a reviewed full commit SHA:

```powershell
python scripts/release_readiness.py --version 5.8.0 --github --expected-commit FULL_COMMIT_SHA
```

The command writes only stdout. Exit 1 means known blockers; exit 2 means
mandatory gate validation remains. It never returns release authorization.
Existing files are labelled `present-unverified`, not passed. GitHub results
are advisory and do not replace authenticated Git provenance, current rules,
signatures, freshness, hardware or manual validation. Duplicate, incomplete,
wrong-head or inaccessible check data stays unverified. It does not inspect
private signing material or run any executable from `dist`.

## Execution sequence and stop conditions

1. Resolve owner distribution decisions in `packaging/license-policy.json` with
   a real root license and hash-bound evidence. Do not choose a project license
   just to satisfy a check. Riverbank's FAQ makes the distribution-license basis
   consequential for PyQt; evaluate the exact bundled licenses and any commercial
   entitlements. [Riverbank licensing FAQ](https://www.riverbankcomputing.com/commercial/license-faq).
2. Restore hosted CI; review and commit the local patch; obtain all exact-head
   checks and merge through protected `main`. Do not disable required checks or
   use a bypass to work around billing. Local tests are useful but not substitutes.
3. Select the signing route, supply protected inputs locally, and follow the
   [canonical blocked-gates runbook](BLOCKED_RELEASE_GATES_RUNBOOK_5.8.0.md):
   finalize, standard-desktop GPU, administrator Compat/manual, verified draft,
   then explicit publication. The unsigned switch must accompany every relevant
   phase and still requires signed updater metadata and all other gates.
4. Require exact-commit hardware evidence, non-skipped owned-lab observations,
   zero owned-process remainder, both frozen variants, and installer fresh-install,
   upgrade, repair and uninstall observations. Exercise backup/restore, diagnostic
   export and cleanup-refused update handoff using the exact packaged product.
   Also exercise account CSV/XLSX import/export, a refused account save, interrupted
   export, legacy-data migration conflicts and malformed-marker recovery.
5. Require current Defender, checksum, SBOM, vulnerability-review, provenance,
   legal/source payload and updater metadata. Download the staged draft and compare
   all uploaded bytes to the validated local set. Rebuild/revalidate if source,
   artifacts, release mode, policy or time-bounded evidence changes.
6. Only after all gates pass, explicitly publish the verified draft. Then download
   the public assets, verify hashes/signatures and test the public updater discovery
   path. GitHub recommends draft-first asset assembly for immutable releases;
   immutability is not assumed or enabled by this plan. [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).

## Launch packet checklist

- Reviewed [draft release notes](v5.8.0.md), with known limitations and the selected
  signed or unsigned/manual-install route stated consistently.
- GPU and Compat downloads, versioned and stable installer names, checksums,
  signed updater metadata, notices, project license, source/relink record,
  exact-source archive, SBOM and release provenance from the verified manifest.
- Clear Windows/Python support claims based on the release test matrix, not on
  packaging-tool compatibility alone. Do not claim that every Windows version,
  GPU, security product or game/server configuration was tested.
- A quick-start path: install, review scope, choose an owned test environment,
  preview diagnostics/dry-run, verify stop/cleanup, and export redacted diagnostics.
- Support instructions: use repository issues for non-sensitive reports; inspect
  redacted bundles before attachment; never request credentials, raw captures or
  private target identifiers in public. No new support address or SLA is promised.
- A maintainer-owned rollback/hotfix decision record and the previous known-good
  release hashes. Do not silently replace published versioned assets.

## Announcement draft - hold until publication verification

> DupeZ v5.8.0 is available for Windows. This release improves backup safety,
> diagnostics privacy, AI request isolation, update responsiveness and release
> integrity for network-condition testing in environments you own or are explicitly
> authorized to test. See the release notes for verified downloads, installation
> guidance, signing status and known limitations.

Before posting, attach the actual verified release URL and selected signing
disclosure. Do not post this draft while any gate above is open. No announcement,
email, issue comment or public release was sent by this preparation work.

## First-launch watch and rollback

- After publication, verify public download/hash/signature continuity, fresh install
  and one supported upgrade path, both variants' startup, cleanup behavior and
  redacted support export. Record observed results without inventing telemetry.
- Stop recommending the new release if installation fails broadly, cleanup cannot
  be confirmed, data integrity is affected, or verification differs from the draft.
  Preserve evidence and diagnose before changing public artifacts or metadata.
- For urgent remediation, issue a reviewed higher-version hotfix through the same
  gates. Any rollback must preserve updater anti-rollback and trust policy; do not
  tell users to disable Defender, signature checks or recovery controls.

The remaining external/owner gates are not implementation failures to hide.
They are the boundary between a prepared source candidate and a launched product.
