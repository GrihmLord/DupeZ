# Changelog

All notable changes to DupeZ are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## v5.7.9 -- 2026-07-18 (Clumsy parity, controller startup recovery, and release integrity)

### Fixed

- **Automatic engine selection now uses the actual bundled Clumsy process for
  exactly representable effects.** Lag, Drop, Disconnect, Duplicate, and RST
  no longer silently take the native path first. DupeZ verifies Clumsy's
  Local/Remote capture layer, module checkboxes, numeric controls, and Start
  state before reporting success. Native WinDivert remains the path for
  native-only behavior and a bounded fallback only where semantics match.
- **Duplicate count parity.** DupeZ defines `duplicate_count` as extra copies,
  while Clumsy counts the original packet. Compatibility mode now translates
  `N` extra copies to Clumsy's `N + 1` total and validates the representable
  range.
- **Split-helper mutations no longer time out during legitimate Clumsy
  startup.** Status queries retain a 5-second bound; engine initialization,
  disruption starts/stops, firewall changes, and shutdown receive a bounded
  30-second response budget.
- **Controller initialization deadlock removed.** Frozen GPU helpers force
  `DUPEZ_ARCH=inproc` before importing architecture-dependent modules, so
  recovery cleanup cannot proxy back into the helper's own named pipe.
- **Packaged Qt startup and build isolation fixed and verified.** Builds
  recreate `.build-venv` from hash-pinned locks, verify `PyQt6.sip`, and
  reject forbidden packages across both PyInstaller archive layers.
- **Single-instance enforcement.** A per-user Windows named mutex prevents
  persistence-lock collisions and helper pipe contention from duplicate GUI
  processes.
- **Startup errors are no longer hidden by the splash screen.** The original
  controller exception and durable log path are preserved; dependent startup
  phases abort, and recovery failures enter an explicit network-disabled safe
  mode.
- **Qt polling no longer blocks on helper IPC.** Dashboard, Clumsy controls,
  and stats refreshes run controller calls outside the UI thread and reject
  stale completions during shutdown.
- **Broken process scoping now fails closed.** WinDivert does not expose
  `processId` at NETWORK/NETWORK_FORWARD packet layers, so non-empty legacy
  `_process_scope` presets are rejected before any engine or ARP state changes.
- **Release sidecars cannot be stale.** Variant builds delete previous update
  manifests before signing, and artifact preflight verifies the pinned
  Ed25519 signature plus manifest version, filename, installer size, and
  SHA-256.

### Verification and provenance

- Bundled `clumsy.exe` is byte-identical to
  `kalirenegade-dev/clumsy` v0.3.4; provenance pins commit
  `bc87e73066168520d76122c9165e99ea703b166c` and the release archive SHA-256.
- Hardware disruption tests now require an explicit private IP and MAC and
  never select the first scanned device. Native module checks require an
  `affected` counter, and a separate opt-in test exercises the real bundled
  Clumsy process/layer/control automation.

---

## v5.7.6 -- 2026-05-27 (Maximum Security Tier 1: Downgrade Replay + Settings HMAC + Audit Seal + Subprocess + Webhook Allowlist)

Closes the five highest-ROI gaps from the post-v5.7.5 security review. Each item closes a concrete attack path that would otherwise survive even with v5.7.5's defense-in-depth posture. No user-visible behavior changes for the normal-operation case -- the work is in fail-closed posture for adversarial paths. See `docs/release-notes/v5.7.6.md` and `docs/adr/ADR-0003-v576-security-hardening.md` for full rationale.

### Security hardening

- **(Item 1) Downgrade-replay protection on the update channel (`app/core/update_state.py`, `app/core/update_verify.py`, `app/core/updater.py`).** Ed25519 manifest signature verifies authenticity, not freshness. An attacker who replays a valid-but-older signed manifest (intercepted CDN, leaked withdrawn release, one-time signing-key compromise) could force every client to "update" backwards into a known-vulnerable version. v5.7.6 adds a HMAC-protected monotonic version ledger at `app/data/update_state.json{,.hmac}`: every successful `verify_manifest` call records the version, every subsequent manifest with a strictly-lower version is refused with a new `DowngradeRefusedError` and a loud `update_downgrade_refused` audit event. Strict semver compare; pre-release / build metadata ignored.

- **(Item 2) HMAC sidecars for `settings.json` (`app/config/__init__.py`).** Pre-v5.7.6, a local attacker (or buggy backup-restore tool) could edit `settings.json` directly and DupeZ would happily load `"kill_switch": false`. Now follows the same sidecar pattern PatchMonitor and `data_persistence.py` already use: every save writes `settings.json` + `settings.json.hmac` atomically (binary mode, tmp + fsync + os.replace) under the per-install `persistence.hmac` secret. On load, mismatched tags quarantine the file as `settings.json.tampered.<ts>` and return `{}`. First-run migration from a v5.7.5 install (file exists, no sidecar) is a one-shot accept-and-sign.

- **(Item 3) Audit log fail-closed on tamper (`app/logs/audit.py`, `dupez.py`).** Pre-v5.7.6 a broken hash chain logged ERROR and silently rotated aside, continuing to write a fresh chain. v5.7.6 seals the logger instead: writes an `audit.TAMPERED` sentinel under the audit directory, refuses every subsequent `log()` call (single stderr warning, then silent drops) until the operator runs `dupez --reset-audit`. The reset archives every audit*.{tampered,corrupted,jsonl} file to `audit-quarantine-<ts>/`, clears the sentinel, and writes a fresh `audit_chain_reset_by_operator` entry as the genesis of the new chain. Pairs with ADR-0002 §6 (fail-closed) -- audit integrity is the record of truth and silent recovery is the wrong default.

- **(Item 4) Subprocess hardening (`app/core/safe_subprocess.py`).** `subprocess.run` and `Popen` calls now pass a Windows `STARTUPINFO` with `STARTF_USESHOWWINDOW | SW_HIDE` (belt on top of `CREATE_NO_WINDOW`) and force `close_fds=True` on every platform including Windows -- the previous `close_fds=(os.name != "nt")` ternary in `spawn_detached` was a Python 3.6-era opt-out that leaked parent handles into detached children on modern Python.

- **(Item 5) Webhook host allowlist (`app/core/audit_webhook.py`, `app/config/audit_webhook_hosts.json` schema).** v5.7.3 closed `file://`/`ftp://`. v5.7.6 also closes `https://attacker.example.com` exfil: webhook hosts now must be in the default Discord allowlist (`discord.com`, `discordapp.com`, `canary.discord.com`, `ptb.discord.com`), in the operator-pinned HMAC-protected list at `app/config/audit_webhook_hosts.json`, or be a loopback address. Off-allowlist hosts are rejected at sink registration time with `WebhookURLError`.

### Tier 1.5

- **(Item 6) `dupez --verify-self` self-integrity check (`app/core/self_verify.py`).** PyInstaller-frozen builds can now verify the running `dupez.exe` against a sidecar `dupez.exe.sig` (Ed25519 signature over SHA-256 of the executable, signed under the same pinned release key as update manifests). Anti-tamper for the binary on disk. Runs explicitly via `--verify-self`; can be wired into the startup probe in a future release.

- **(Item 7) `dupez --reset-audit` CLI flag (`dupez.py`).** Operator escape hatch paired with Item 3. Archives the suspect chain and unseal the logger.

- **(Item 8) Cert-pinning helper (`app/core/cert_pinning.py`).** SPKI-pinning infrastructure for the auto-updater's GitHub Releases calls. **Ships in audit-only mode for v5.7.6**: the `PINS` map is empty by default and every cert chain observed during update calls emits a `cert_chain_observed` audit event so the release engineer can populate the pin set in v5.7.7. `DUPEZ_DISABLE_CERT_PIN=1` is the bypass escape hatch for the recovery path if a future CA rotation breaks the pins. Shipping known-good pins straight from the gap-analysis spec would brick the updater if the SPKI values were wrong; staged rollout is the correct posture for a pin set.

### Test coverage

`tests/test_security_v576.py` adds seven test classes covering the v5.7.6 invariants:

- `TestDowngradeReplay`         -- semver compare, ledger persistence, monotonic floor, HMAC mismatch defaults to 0.0.0.
- `TestSettingsHmacSidecar`     -- roundtrip writes sidecar, tampered payload quarantines + returns {}, first-run migration.
- `TestAuditFailClosed`         -- clean chain logs, tampered terminal seals, sealed logger drops writes, reset archives + unseals.
- `TestSubprocessHardening`     -- `subprocess.run` receives `close_fds=True` + STARTUPINFO on Windows; `spawn_detached` likewise.
- `TestWebhookHostAllowlist`    -- Discord accepted, loopback accepted, off-allowlist rejected, test-env hosts work, file:// still rejected.
- `TestSelfVerify`              -- dev-mode source-tree returns ok=True with "skipped".
- `TestCertPinningHelpers`      -- empty-set audit-only, mismatch raises, match accepts, env disable bypasses.

`tests/conftest.py` sets `DUPEZ_TEST_WEBHOOK_HOSTS` at session start so existing webhook tests against `example.invalid` keep passing.

### Lockstep version bump

`app/__version__.py`, `packaging/version_info.py`, `packaging/dupez.manifest`, `packaging/dupez_compat.manifest`, `packaging/installer.iss`, `packaging/build.bat`, `packaging/build_variants.bat`, `README.md`, `CHANGELOG.md`.

### Deferred (v5.8.x)

ADR-0003 documents the four items deferred to v5.8.x: real AppContainer / Job Object enforcement for plugins (currently declarative), DPAPI scope audit (`CRYPTPROTECT_LOCAL_MACHINE = 0`), memory-safe secret handling via `SecretBytes`, and WER opt-out for the elevated helper.

---

## v5.7.5 -- 2026-05-27 (WiFi Disrupt Audit Closure: MAC Scrubber + Resource Hygiene)

Follow-up hardening pass closing the actionable MEDIUM and LOW findings from `docs/audits/WIFI_DISRUPT_AUDIT_v5.7.4.md`. The four HIGH findings (H1-H4) were already closed in v5.7.3/v5.7.4; this release closes M1, M2, M6, L2, L3, and adds a defense-in-depth MAC scrubber at the logger layer. No user-visible behavior changes -- the work is in failure-mode honesty, resource hygiene, and opsec.

### Defense in depth

- **MAC scrubber at the `ScrubbingFormatter` layer (`app/utils/helpers.py`, `app/logs/logger.py`).** New `mask_macs_in_text()` helper, wired into `_scrub_log_message()`. Every log line written to disk or console is now scrubbed of raw MAC addresses regardless of whether the call site remembered to call `mask_mac()`. OUI prefix preserved (vendor identification is public via IEEE registry); trailing three octets -- the device-unique part -- replaced with `**:**:**`. Companion to the existing `mask_ips_in_text()`.

### Fixed (audit closure)

- **(M1) `atexit.register(spoofer.stop)` registered when ARP spoofing starts (`app/firewall/clumsy_network_disruptor.py`).** Best-effort ARP cache restoration on uncaught exceptions, `sys.exit()`, and Ctrl+C. Previously a mid-session crash left the target poisoned, black-holing its gateway traffic for 30-60s until the ARP entry aged out. Does not cover `kill -9` / SIGSEGV (tracked for v5.8.x hot-reload guard) but covers every clean-shutdown failure mode.

- **(M2) `_is_wifi_same_network` reads the actual interface netmask (`app/firewall/target_profile.py`).** Previously hardcoded `/24`, which silently misclassified targets on `/23` or `/22` LANs (Eero mesh, business APs) as "not same-network" -- they fell through to NETWORK layer with the wrong target, silent no-op disrupt. New `_local_network_for_ip()` helper reads the netmask via `psutil.net_if_addrs()`, falls back to `/24` only when unavailable.

- **(M6) `NpcapSender` context manager + defensive `__del__` (`app/network/arp_spoof.py`).** Partial-init failures (`load()` succeeded, `open()` raised) no longer leak the pcap handle. `with NpcapSender() as sender:` is now supported; `__del__` is the GC-time safety net. Both call `close()` idempotently.

- **(L2) `ArpSpoofer.__init__` validates `target_ip` and `gateway_ip` (`app/network/arp_spoof.py`).** Malformed IPs now raise `ValueError` immediately with a clear message instead of propagating through `arp -a`, `ping`, and `socket.connect` to surface as a generic "cannot resolve MAC" after 3+ subprocess invocations.

- **(L3) `_poison_loop` self-terminates after persistent send failures (`app/network/arp_spoof.py`).** New `_POISON_FAILURE_THRESHOLD = 5` constant; after 5 consecutive `_poison_once()` raises (typical sign of a dead Npcap handle), the loop logs CRITICAL and sets `_running = False`. Previously the loop would spin forever logging an error every cycle while the disruptor still reported the spoofer as ACTIVE -- exactly the silent-fail pattern v5.6.4 was meant to eliminate.

### Test coverage

`tests/test_ip_leak_guard.py` extended with `TestMacScrubber`, `TestTargetProfileNetmask`, and `TestArpSpooferValidatesIp` test classes -- four new tests total locking down the v5.7.5 invariants.

### Deferred to v5.8.x

The remaining audit items (`M3` watchdog cancel-vs-fire race, `M4` watchdog thread join, `M5` `clear_all_disruptions_clumsy` error aggregation, `L1` netsh locale parsing, `L4` doc comments, `L5` taskkill warning logs) need the `WifiDisruptSession` orchestration class from architecture recommendation #5 to close cleanly. Tracked for the v5.8.x quality-debt pass already on the roadmap.

---

## v5.7.4 — 2026-05-24 (Wire-Up: Orphaned Feature Backends Now Reachable)

A deep audit found that seven feature backends shipped across v5.7.0 and v5.7.1 were never wired to an invocation point. They were tested, documented in the CHANGELOG as shipped features, and the release notes said "UI lands next release" — but v5.7.1 became a codebase-quality pass and the wiring never happened. The result: ~2000 LOC of working, tested code that a user could not actually invoke. v5.7.4 closes that gap.

### How the gap happened
v5.7.0 explicitly deferred UI wiring to v5.7.1 ("backend ready, UI lands in v5.7.1" appears verbatim in the v5.7.0 release notes). v5.7.1 was then re-scoped to a quality/test pass and shipped without the deferred wiring. No audit caught it until now because every module compiled, every module had unit tests, and the CHANGELOG described the features as done — nothing flagged "this backend has zero callers."

### Fixed — features now actually reachable
- **Audit webhook fan-out (`app/logs/audit.py`).** `AuditLogger.log()` now calls `audit_webhook.emit_to_sinks()` after the canonical JSONL write. Pre-v5.7.4 a configured Discord/generic webhook received nothing — `emit_to_sinks` had zero callers. The fan-out is best-effort, daemon-threaded, and cannot raise into the audit hot path.
- **Episode-store rotation (`app/main.py` Phase 4b).** `rotate_episodes()` now runs once per launch, enforcing the 90-day / 5000-file retention policy added in v5.7.1. Pre-v5.7.4 the function existed but was never called — the episode JSONL store grew unbounded.
- **Audit webhook sink registration (`app/main.py` Phase 4b).** On startup DupeZ reads `settings.audit_webhook` and registers a `DiscordWebhookSink` / `GenericWebhookSink` when configured + enabled. Combined with the fan-out above, the webhook feature is now end-to-end functional.
- **OBS overlay server (`app/main.py` Phase 4b + Tools menu).** Auto-starts on launch when `settings.obs_overlay_enabled` is set; a "Toggle OBS Overlay Server" Tools-menu entry starts/stops it on demand and shows the browser-source URL. Cleanly stopped on shutdown. Pre-v5.7.4 `OverlayServer` was never instantiated.
- **Risk score (`app/gui/dashboard.py` Tools menu).** New "Risk Score…" entry computes and displays the 0-100 score with its full six-factor breakdown. Pre-v5.7.4 `compute_risk_score()` was computed only as an input to other orphaned modules — never shown to the operator.
- **Diagnostic wizard (`app/gui/dashboard.py` Tools menu, F2).** New "Diagnostics…" entry runs all 8 self-checks and displays pass/warn/fail with remediation hints. Pre-v5.7.4 `run_all_checks()` had no UI entry point.
- **Kill switch panic-stop (`app/gui/dashboard.py` Tools menu, Ctrl+Alt+X).** New "Kill Switch — Panic Stop" entry immediately halts all disruptions. This is the operator-essential half of the kill-switch feature.

### Also fixed (triple-check pass)
- **`OverlayServer.start()` reported success on a failed bind (`app/core/overlay_server.py`).** It returned `None` whether the port bound or not, so both the startup autostart and the Tools-menu toggle claimed "overlay started" even when the port was already in use. `start()` now returns `bool`; both callers check it and report honestly. Added a `running` property and two regression tests.
- **`scripts/release.ps1` added.** The hand-typed release sequence silently mis-tagged four releases (v5.6.3, v5.6.5, v5.7.1 ×2): a pre-commit hook fails → `git commit` exits non-zero → PowerShell keeps going → `git tag` lands on the previous release's commit. The new driver checks `$LASTEXITCODE` after every step, asserts HEAD actually moved after the commit and the tree is clean, asserts the tag dereferences to the merged commit, and aborts on the first failure before anything irreversible. `scripts/README.md` updated to document it + the rest of the scripts directory.
- **Help docs described a removed feature (`app/gui/panels/help_panel.py`).** Reported by a user: the Getting Started and Clumsy Control sections told operators to select a "Dupe" preset and pick a method from a "DUPE METHOD" card (Clone, Drop & Pick, Swap, Container, Rift, Legacy). None of that exists — `DupeEngineV2` and its method card were removed and duplication now runs through the **Red Disconnect** preset's stateful DISCONNECT timed-cut module, but the help panel was never updated. The three preset lists now match the actual `PRESETS` dict (Red Disconnect, Lag, God Mode, Custom); the "Dupe Engine v2" section was rewritten as "Duplication Workflow — The Timed Cut", describing the real arm → cut → release mechanism and the Arm Delay / Duration / TIMED DISRUPT controls. A stale `Dupe Engine v2` comment in `_packet_utils.py` was also corrected. No code behavior changed — this is a documentation-accuracy fix only.

### Also fixed (doc-vs-reality audit)
A follow-up audit — triggered by the same user report — checked every claim in the in-app help against the actual code. Seven more drift items, all fixed; no code behavior changed except the hotkey dialog (now self-generating, see below).
- **Help "Voice Control" pointed at a settings tab that does not exist (`help_panel.py`).** It said "Tools → Settings → Voice tab"; the Settings dialog has no Voice tab. Voice control is the Voice panel in the **Network Tools → AI / Smart Ops** tab. Corrected.
- **Help "GPC / Cronus Zen" pointed at the sidebar (`help_panel.py`).** It said the GPC panel appears in the sidebar; GPC is the **GPC / Cronus Zen** tab in the Network Tools view. Corrected.
- **Help "SMART DISRUPT" described a control that is not in that view (`help_panel.py`).** The feature is **Smart Mode** — a tri-state (off/learn/assist) in the Network Tools → AI / Smart Ops tab, not a control in Clumsy Control. Renamed and relocated in the text.
- **Help "Disruption Modules" list was missing three modules (`help_panel.py`).** DISCONNECT, BANDWIDTH, and TCP RST are in `MODULE_DEFS` but were absent from the help list — DISCONNECT being the duplication module makes that omission notable. All nine modules are now listed; the PLATFORM card was also added to the Clumsy Control section.
- **Help "Keyboard Shortcuts" table was missing ten shortcuts (`help_panel.py`).** It listed 6; the menu bar registers 15 (plus the Ctrl+Shift+D tray toggle). The view-switch keys (Ctrl+1–4), preset editor (Ctrl+Shift+P), account cycling (Ctrl+Alt+A / Ctrl+Alt+Shift+A), Diagnostics (F2), and Kill Switch (Ctrl+Alt+X) were all undocumented. The table now lists all 16.
- **Hotkey reference dialog rebuilt to self-generate (`app/gui/dashboard.py`).** `_show_hotkeys` (Help → Hotkeys, F1) was a third, separately-stale hand-typed list. It now generates itself from the live menu-bar `QAction`s, so it can never drift again.
- **README corrected (`README.md`).** It listed Auto-Tune / Voice / GPC as Clumsy Control cards (they are not) and called Network Tools "four-tab" (four core + up to three conditional). Both corrected. A stale `clumsy_control.py` module docstring and a stale `native_divert_engine.py` comment were fixed too.

**Guard against recurrence:** `tests/test_doc_drift_guard.py` (4 tests) now cross-checks `help_panel.py` against `PRESETS`, `MODULE_DEFS`, and the dashboard menu shortcuts on every CI run — parsed via `ast`, no Qt import. It fails the build if the help panel names a removed feature, omits a real preset/module, or disagrees with the menu about shortcuts. This is the structural fix: the doc-drift class of bug — which has now produced two separate user-visible failures — can no longer reach a release.

### Also fixed (functional bug audit)
A third audit pass — parallel deep-dive subagents over the v5.6.9–v5.7.4 modules — found five genuine runtime bugs. All fixed, each with a regression test (suite: 601 passing).
- **`cut_chain.py` measured time on the wall clock.** Every duration and deadline (`global_timeout`, the time gate, the A2S and packet gate timeouts) used `time.time()`, which jumps on NTP sync / DST / manual clock changes — a jump mid-chain could fire a timeout instantly or never. Switched to `time.monotonic()` throughout. Separately, the time gate accumulated a fixed `0.1s` tick into an `elapsed` counter instead of measuring real elapsed time, so a "7s" gate drifted noticeably long; it now waits against a monotonic deadline.
- **`kill_switch.py` could run two poll threads at once.** `stop()` nulled the thread reference unconditionally — even when the 2s join timed out and the thread was still alive — and `start()` only checked `_thread is not None`. A `stop()`/`start()` cycle under a slow tick spawned a second poll thread; the two then raced on `_last_fire_ts`. `start()` now guards on `is_alive()`; `stop()` only clears the reference once the thread has actually exited.
- **`patch_monitor.py` discarded the whole patch feed on one bad date.** A non-numeric or absurd Steam `date` field fed straight into `datetime.fromtimestamp()` raised inside the item loop, and the broad `except` in `_fetch_news` then dropped *every* patch in the batch. The date is now coerced safely and the timestamp conversion is guarded per-item — one malformed item no longer poisons the fetch.
- **`patch_monitor.py` background loop could busy-spin.** `range(int(self._check_interval))` truncates a fractional interval to `0`, turning the responsive-sleep loop into a no-delay hammer on the Steam API. Guarded with `max(1, …)`.
- **`risk_score.py` cut-compression factor could never reach its cap.** `_compression_contribution` divided the close-pair count by the *timestamp* count (N) instead of the *pair* count (N-1), so a fully-compressed cut history topped out at `(N-1)/N` of the cap — it could never push that factor to RED, even though the detail string already read "N-1/N-1". Off-by-one corrected.

Audit also confirmed clean: the v5.7.4 settings keys (`audit_webhook`, `obs_overlay_enabled`) resolve correctly against the free-form settings store, the Phase 4b wiring is sound, and `preset_store` / `backup` / `overlay_server` / `audit_webhook` / `diagnostics` have no functional bugs. A separate orphaned-symbol scan found no further wire-up gaps — the remaining zero-caller symbols are crypto/validation library helpers, not unreachable features.

### Also fixed (IP-leak audit)
A pass over every path an IP address can leave the process — logs, the audit trail, the Discord webhook, the OBS overlay — found two real leaks. A new shared masker, `mask_ips_in_text` (`app/utils/helpers.py`), masks the last octet of every IPv4 address found anywhere in a string (bare *or* embedded in prose) and is now applied at every egress point.
- **Session logs wrote raw IP addresses (`app/logs/logger.py`).** `_scrub_log_message` — on the hot path for every log line — only scrubbed secrets, not IPs, so `ArpSpoofer`, `[VERIFY]`, `[LAN CUT]` and similar lines wrote full device IPs into `logs/*.log`, which users routinely share for support. It now masks IPs too. Separately, the `error()` / `critical()` exception path bypasses that scrubber entirely; a new `_ScrubbingFormatter` is attached to every handler so the message, the context, and the rendered `exc_info` traceback are all scrubbed regardless of code path — no log line can carry a raw IP or a credential.
- **The audit JSONL masked IPs only under known key names (`app/logs/audit.py`).** `_scrub_pii` masked values under `ip` / `target_ip` / `src_ip` / `dst_ip` but returned every other string untouched — an IP under any other key, or embedded in a message, was written verbatim to `audit.jsonl`, which is bundled into the shareable backup zip. It now masks IPs in every string value.
- **Webhook hardening (`app/core/audit_webhook.py`).** `_scrub` already masked bare-IP values before posting to Discord; it now also masks IPs embedded inside longer strings, closing the same gap as the audit fix.

Confirmed already safe: the OBS overlay `/state` snapshot masks `target_ip` before serving it (the overlay is rendered on-stream), the episode-recorder JSONL stores no IP addresses, and the repository has no hardcoded public IPs.

**Guard against recurrence:** `tests/test_ip_leak_guard.py` (8 tests) asserts each egress scrubber — session log, audit JSONL, webhook, overlay snapshot — masks both bare and embedded IPs on every CI run.

### Still backend-only (documented, not yet wired — honest accounting)
- **Cut chaining (`CutChainRunner`).** Genuinely needs a multi-stage configurator dialog (add/reorder/remove stages, per-stage gate selection). Deferred to a future release rather than shipped as a half-built UI.
- **Kill-switch trigger orchestrator (`KillSwitch` class).** The manual panic-stop is wired (above); the auto-trigger config (anti-cheat process watch, risk-threshold, packet-rate) needs a settings panel. The panic button — the part that matters in a hurry — works now.

### Test plan
- Configure `settings.audit_webhook = {"enabled": true, "url": "https://discord.com/api/webhooks/...", "kind": "discord"}`, fire a cut, confirm a Discord embed arrives.
- Launch, confirm log line `Episode rotation: pruned N stale file(s)` (or silence when nothing is stale).
- Tools → Risk Score… — confirm the score dialog with factor breakdown.
- Tools → Diagnostics (F2) — confirm 8 checks render.
- Tools → Kill Switch — Panic Stop (Ctrl+Alt+X) — confirm all disruptions halt.
- Tools → Toggle OBS Overlay Server — confirm the URL dialog; open it in a browser; confirm the overlay renders.

---

## v5.7.3 — 2026-05-13 (Security Hardening: v5.6.9-v5.7.2 Modules)

The original nation-state cert sweep (v5.6.2, task #28) covered the codebase as it stood then. The eleven modules added afterward — preset store, process scope, backup, risk score, kill switch, diagnostics, audit webhook, cut chain, overlay server, account quick-switch, wifi probe — were never security-reviewed. v5.7.3 closes that gap. Five findings, one critical.

### Fixed — CRITICAL

- **Backup restore could overwrite source code → arbitrary code execution (`app/core/backup.py`).** `restore_backup` walked the manifest of whatever bundle it was handed and wrote every entry, gated only by a repo-root path-traversal check. That check stops escaping the repo — it does NOT stop a hand-crafted malicious bundle from containing an entry like `app/core/clumsy_network_disruptor.py` or `dupez.py` with attacker code, which would execute on the next launch. A backup shared via Discord (the encrypt mode is explicitly designed for sharing) was a code-execution vector. **Fix:** restore now enforces a path allowlist — only `app/data/` and `app/config/` entries are restorable. Executable code and packaging files are refused. A legitimate DupeZ bundle only ever contains allowlisted paths, so this never rejects a genuine backup.

### Fixed — MEDIUM

- **Backup decompression-bomb exposure (`app/core/backup.py`).** `restore_backup` / `list_bundle` read whole ZIP entries into memory with no size ceiling — a 50 KB bundle could decompress to exhaust RAM and disk. **Fix:** per-entry cap (512 MB) + total-bundle cap (2 GB), enforced from both the manifest-stated size AND the actual decompressed bytes (catches a lying manifest).
- **Overlay server leaked disruption state cross-origin (`app/core/overlay_server.py`).** The `/state` endpoint sent `Access-Control-Allow-Origin: *`, so any website the operator visited in a normal browser could `fetch('http://127.0.0.1:4778/state')` and read whether DupeZ was running, what it was targeting, and the live risk score. **Fix:** wildcard CORS header removed entirely — the OBS browser source loads `overlay.html` directly so its `/state` calls are same-origin and need no CORS grant. Added `X-Content-Type-Options: nosniff`.
- **Webhook URL accepted dangerous schemes (`app/core/audit_webhook.py`).** `urllib.request.urlopen` honors `file://`, `ftp://`, `gopher://` etc. A webhook URL set (or imported) as `file:///C:/Users/.../secrets.enc.json` would be opened by the sink. **Fix:** `_validate_webhook_url` enforces `https://` only, with `http://` permitted solely for loopback hosts. Validated at sink construction — a sink can never exist with a dangerous URL. New `WebhookURLError`.
- **Preset params could inject engine control flags (`app/core/preset_store.py`).** A preset's `params` dict is user-authored, SHARED data (export/import sidecars, future marketplace). Underscore-prefixed keys are engine-internal control flags (`_network_local`, `_force_arp_spoof`, `_force_self_disrupt`, `_wifi_auto_fallback`, `_target_ip`). A malicious shared preset carrying `{"_network_local": true}` could silently flip engine behavior on the importer's machine. **Fix:** preset validation now allowlists underscore keys — only `_ports` and `_process_scope` (documented preset features) are permitted; any other `_`-prefixed key is rejected. Added a 16 KB cap on the serialized params dict (a preset is small config, not a data blob).

### Fixed — LOW (documentation hardening)

- **Diagnostics `fix_command` execution contract (`app/core/diagnostics.py`).** The `fix_command` field carries shell/PowerShell snippets. Today every value is a compile-time constant so there is no injection vector, but a future check could compute one from a path. Added an explicit SECURITY CONTRACT to the module docstring: `fix_command` is display-only and MUST NEVER be auto-executed by the UI. This makes the "display, never run" rule absolute so no future check author can accidentally open a command-injection sink.

### Added
- **`tests/test_security_v573.py`** — 15 security regression tests, one cluster per finding: backup path-allowlist (refuses to overwrite source, allows data paths), overlay no-CORS-wildcard, webhook scheme validation (file/ftp/remote-http rejected, https/localhost-http accepted), preset underscore-key allowlist + params size cap. Locks every fix so the holes cannot silently reopen.

### Test suite
- 570 → 585 passing (+15 security tests).

### Test plan
- `python -m pytest tests/test_security_v573.py -q` — all 15 pass.
- Hand-craft a bundle with an `app/core/x.py` entry, attempt `restore_backup` — confirm it is skipped, not written.
- Configure an audit webhook with a `file://` URL — confirm `WebhookURLError` is raised at sink construction.
- Import a preset JSON whose params contain `_network_local` — confirm the import is rejected.
- `curl -H "Origin: https://evil.example" http://127.0.0.1:4778/state` — confirm no `Access-Control-Allow-Origin` header in the response.

---

## v5.7.2 — 2026-05-13 (Regression Fix: WiFi Disruption of Peer Devices)

A user reported a real regression: after updating to v5.7, scanning the WiFi network still found every device (including their Xbox) but firing DISRUPT had no effect — where pre-v5.7 it disconnected and lagged the target normally. This release reverts the decision that caused it.

### The bug

v5.6.5 made "self-disrupt" the default for same-WiFi targets — DISRUPT would only affect the operator's OWN machine's traffic to/from the target, never the target device itself. The reasoning at the time (AP client isolation makes ARP spoof unreliable; most users want to lag their own connection to a server) was wrong about the primary workflow: when an operator picks an Xbox / PS5 / PC from the network scan and clicks DISRUPT, they want to disrupt **that device**. Self-disrupt does nothing they asked for. v5.6.5 silently turned the tool's core function into a no-op for peer targets.

### Fixed
- **Same-WiFi peer targets route through ARP spoof again (`app/firewall/target_profile.py`).** `resolve_target_profile` now returns `layer="forward"`, `needs_arp_spoof=True` for `wifi_same_net` targets — the pre-v5.7 behavior that worked. The target device's traffic is redirected through the operator's machine and disrupted directly.
- The v5.6.5 isolation watchdog is **kept and now actually runs by default** — when the AP genuinely has client isolation and drops the spoof, the watchdog detects zero forwarded packets and auto-falls-back to self-disrupt mode with a toast. Users without isolation get the working ARP cut; users with isolation get an honest fallback. Nobody gets a silent no-op.
- The v5.6.4 honesty guards (return False → "Partial Failure" dialog on Npcap-missing / ArpSpoofer-start-failure) remain in place — a misconfigured host still surfaces the error.

### Changed
- **Isolation watchdog grace window raised 5s → 8s (`app/network/wifi_probe.py`).** The watchdog can't perfectly distinguish "AP dropped the spoof" from "target console briefly idle in a menu, no traffic to forward yet" — both look like `packets_sent > 0, packets_processed == 0`. The longer window errs toward not bouncing a working-but-quiet cut to self-disrupt. Still fast enough to catch genuine isolation. Configurable via `params["_wifi_isolation_grace_s"]`.
- **`params["_force_self_disrupt"]` now honored (`app/firewall/clumsy_network_disruptor.py`).** Operators who specifically want to lag only their own connection to a target (e.g. a shared game server) can pass this flag — it forces NETWORK layer and skips ARP spoof regardless of detection. This is the documented escape hatch; self-disrupt is no longer the forced default.
- Help panel WiFi section rewritten to describe the corrected v5.7.2 behavior.

### Added
- **Regression test (`tests/test_target_profile_detection.py`).** `test_wifi_same_net_uses_arp_spoof_and_forward_layer` asserts `wifi_same_net` resolves to `layer="forward"` + `needs_arp_spoof=True`. Locks the corrected behavior so this regression cannot return silently. Test suite: 569 → 570.

### Upgrade note for affected users
If you're on v5.7.0 or v5.7.1 and disruptions stopped working on WiFi peer devices, v5.7.2 restores them. Auto-update (v5.6.6+) will install it automatically. If the cut still has no effect after updating, you have AP client isolation — the watchdog will show an "AP isolation detected" toast; disable "Client Isolation" in your router's WiFi settings, or connect the operator PC via Ethernet.

### Test plan
- Build: `packaging\build_variants.bat`. Confirm 5.7.2.0.
- WiFi same-net peer target (Xbox/PS5/PC) on a router WITHOUT client isolation: fire Red Disconnect. Expected: ARP spoof starts, target's connection lags/drops — restored pre-v5.7 behavior.
- WiFi same-net target on a router WITH client isolation: fire Red Disconnect. Expected: ARP spoof starts, watchdog detects no forwarded packets after 8s, toast announces self-disrupt fallback.
- `params["_force_self_disrupt"] = True`: confirm NETWORK layer, no ARP spoof, only operator's own traffic affected.
- Hotspot mode (PS5/Xbox via ICS): unchanged.

---

## v5.7.1 — 2026-05-13 (Codebase Quality Pass: Tests + Bugs + Docs)

Pure quality release — no new features. The audit pass over the v5.6.9 + v5.7.0 modules surfaced three real production bugs and zero test coverage on the 10 newly-shipped modules. v5.7.1 backfills the test suite from 386 → 569 passing tests, fixes the bugs the new tests uncovered, adds episode-store rotation to prevent unbounded growth, and consolidates the major architecture decisions into a single ADR.

### Fixed (real bugs the audit found)

- **Audit webhook rate-limiter started empty (`app/core/audit_webhook.py`).** Pre-v5.7.1 `_TokenBucket` defaulted `tokens=0.0`. A newly-registered sink silently dropped every event for the first `60/refill_per_min` seconds (default 1 second) before the bucket accumulated tokens. Surfaced by `test_emit_does_not_block`. Bucket now starts full (`tokens=capacity`) — first events deliver immediately, sustained bursts still rate-limit correctly. Added `test_starts_full` + `test_drains_to_zero` to lock the contract.
- **Custom preset name regex rejected auto-rename suffix (`app/core/preset_store.py`).** `_NAME_RE` allowed alphanumerics + space + underscore + dash, but NOT parentheses. The same module's `import_preset` generates collision-resolution names like `Conflict (2)`, which then failed validation on save — every duplicate-import crashed. Regex now includes `()`; the new suffix scheme works end-to-end. Added `test_name_with_parentheses_accepted`.
- **Overlay handler class-attribute leak (`app/core/overlay_server.py`).** Two `OverlayServer` instances on different ports would clobber each other's controller reference (last-writer-wins) because the handler stored the controller as a class attribute. Refactored to a per-instance handler factory (`_make_handler_class`). Caught in the v5.7.0 audit, locked down by `test_handler_classes_are_distinct_types` in v5.7.1.

### Added (testing + retention infrastructure)

- **Episode store rotation (`app/ai/episode_recorder.py`).** New `rotate_episodes()` function with two-pass policy: age-cap (default 90-day retention) AND count-cap (default 5000-file ceiling). Operators with long-running installs no longer accumulate unbounded JSONL files. Safe to call from a background thread; never raises. Test coverage: `tests/test_episode_rotation.py` (10 tests covering age cap, count cap, oldest-first ordering, missing-dir safety, non-episode files preserved, combined age+count behavior).
- **Unit tests for all 10 v5.6.9 + v5.7.0 modules.** 175 new test cases:
  - `test_preset_store.py` — 22 tests (validation, round-trip, import-collision, export sidecars)
  - `test_process_scope.py` — 13 tests (filter-clause construction, scope branches)
  - `test_backup.py` — 9 tests (round-trip, manifest, hash-mismatch refusal, path traversal)
  - `test_risk_score.py` — 26 tests (per-factor scaling, band classification, edge cases)
  - `test_kill_switch.py` — 12 tests (trigger types, cooldown, disabled-but-manual override)
  - `test_diagnostics.py` — 7 tests (registry, run-all, individual lookups)
  - `test_audit_webhook.py` — 23 tests (token bucket, scrub, IP detection, sink registry, async dispatch)
  - `test_cut_chain.py` — 9 tests (stage walk, gate kinds, failure modes)
  - `test_overlay_server.py` — 12 tests (snapshot composition, handler isolation, live HTTP)
  - `test_account_quick_switch.py` — 12 tests (get/set/cycle/clear lifecycle with mocked persistence)
- **ADR-0002 consolidating architectural decisions (`docs/adr/`).** Captures the WHY of WiFi self-disrupt default, auto-update fail-closed, split-elevation architecture, local-only telemetry, plugin trust model, fail-closed posture, test-coverage policy, and feature-creep boundaries.

### Test suite numbers

- **Pre-v5.7.1:** 386 passing tests, 4 skipped, 1 environmental fail. ~25 test files for 151 source files.
- **Post-v5.7.1:** 569 passing tests, 4 skipped, 1 environmental fail. 11 new test files; every v5.6.9/v5.7.0 module now has dedicated coverage.

### Quality-debt items deferred (documented for future cycles)

The audit identified additional opportunities not addressed in v5.7.1 because the impact-per-hour ratio favored shipping tests + bug fixes first. Tracked for v5.8.x:

- 396-line + 353-line try/except blocks in `native_divert_engine.py` and `clumsy_network_disruptor.py` — should be decomposed into phase methods for crash localization.
- Four files >1500 LOC (`clumsy_control.py` 2077, `clumsy_network_disruptor.py` 1976, `native_divert_engine.py` 1818, `dayz_account_tracker.py` 1800) — god-object refactors.
- Performance hot-path: `for mod in self._modules:` per-packet loop could be replaced with a precompiled chain function (~20-40% throughput estimate).
- 673 broad `except Exception` callsites — sample and narrow the highest-risk ones.

### Test plan

- `python -m pytest tests/ -q` — confirms 569 passing, 1 sandbox-environmental fail.
- `python -c "from app.ai.episode_recorder import rotate_episodes; print(rotate_episodes('app/data/episodes', retention_days=90, max_files=5000))"` — runs the rotation against the live install (reports count removed, doesn't error).

---

## v5.7.0 — 2026-05-12 (Telemetry + Safety + Polish: Seven New Modules)

Bundles what was originally scoped as v5.7.0 (telemetry + safety) and v5.7.1 (polish) into a single release. All seven features share the same backend infrastructure pattern — standalone modules that wrap existing engine + telemetry surfaces rather than introducing new disruption capability — so shipping them together keeps the changelog readable and avoids two consecutive build cycles for what is logically one release.

### Added — telemetry + safety

- **Risk score aggregator (`app/core/risk_score.py`).** Single 0-100 number derived from six weighted inputs: recent cut rate (30-min window), failure streak (last 5 labeled), overall success-rate shortfall, cut-compression (cuts <60s apart), never-cut ratio (engine started but A2S never severed), audit-log activity volume. Bands: GREEN 0-29, AMBER 30-69, RED 70-100. Returns a `RiskScore` with per-factor breakdown for the UI. All inputs come from existing telemetry — zero new sensors. Self-tested against Grihm's real episode store: pulled 54 (amber) on first call from 122 episodes, surfacing the "100% never-cut" signal that previously had no UI surface.
- **Kill switch with trigger-based auto-stop (`app/core/kill_switch.py`).** Daemon-threaded orchestrator that polls N triggers and calls `controller.stop_all_disruptions()` on fire. Ships with four trigger types: `AntiCheatProcessTrigger` (psutil-based watch for BattlEye / EAC / Vanguard / GameGuard etc.), `RiskScoreTrigger` (auto-stop when risk crosses threshold), `PacketCounterTrigger` (token-bucket-style runaway-drop detection), `ManualTrigger` (programmatic fire from UI / hotkey). Per-trigger cooldown prevents fire loops while the operator restores state.
- **Diagnostic wizard backend (`app/core/diagnostics.py`).** Eight self-checks consolidated into a registry: admin privileges, WinDivert files, Npcap availability, clumsy.exe fallback, auto-update pubkey provisioned, data directory writability, Windows Defender posture (best-effort hint), episode store presence. Each check returns a `CheckResult` with status (PASS/WARN/FAIL), human message, fix hint, and optional shell command for one-click remediation. Powers the new "Tools → Diagnostics…" menu (UI dialog can be wired in v5.7.1 — backend ready).
- **Discord (and generic) webhook audit sink (`app/core/audit_webhook.py`).** Fans out `audit_event` payloads to user-configured webhook URLs after the canonical JSONL write succeeds. Default event whitelist (cut_start/cut_end/outcome/flow_health_miss/killswitch_fired/disruption_start/disruption_stop) keeps the firehose readable. Per-sink token-bucket rate limit (default 30/min) prevents Discord rate-limit hits. IP scrubbing reuses existing `mask_ip` helper as defense-in-depth. Discord shape produces colored embeds; `GenericWebhookSink` emits raw JSON for Slack/Mattermost/Telegram bots.

### Added — orchestration + UX polish

- **Cut chaining (`app/core/cut_chain.py`).** Sequence N presets against a target with operator-configurable timing gates. Gate kinds: `time` (wait N seconds), `severed` / `connected` (wait for A2S verifier state with fallback timeout), `packets` (wait until engine processed N packets). `ChainConfig` declares stages + `on_failure` (halt / continue / rewind) + global timeout. `CutChainRunner` daemon-threads the walk, emits `ChainEvent` per stage transition. Self-tested with a fake controller — emits stage_start/stage_end/complete in correct sequence.
- **Multi-account quick-switch (`app/core/account_quick_switch.py`).** Persistent "active account" marker stored at `app/data/active_account.json`. Episode recorder + audit log can consume `get_active_account()` to tag entries with the operator's currently-selected tracker account. `cycle_active_account(direction)` for a forward/backward hotkey (UI binding lives in v5.7.x). Refuses to set an active name not present in the tracker — prevents phantom tagging from typos.
- **OBS overlay HTTP endpoint (`app/core/overlay_server.py`).** Tiny localhost HTTP server (default 127.0.0.1:4778) exposing two endpoints: `GET /state` returns JSON snapshot of active targets + risk score; `GET /overlay.html` serves a self-contained HTML page that polls `/state` every 1s and renders an overlay (drop into OBS as a Browser Source). Bound to loopback by default — no LAN exposure unless explicitly reconfigured. Read-only, no write endpoints. CORS allowed so OBS Browser Source can fetch without friction.

### Engine notes

- All seven new modules are standalone-importable + unit-testable. Smoke coverage in this release: risk-score factor decomposition, kill-switch manual-trigger fire, diagnostics 8-check run with status validation, audit webhook sink registration + scrub, cut-chain stage walk against fake controller, overlay snapshot composition, active-account validation.
- No engine changes. The four v5.6.9 engine extensions (preset editor / per-port / process scope / backup) remain the integration layer; v5.7.0 sits above them.
- No new third-party dependencies. Everything reuses existing stdlib + psutil (already in requirements).

### Test plan

- Risk score: open Tools menu → "Risk Score…" (wire pending) or run `python -c "from app.core.risk_score import compute_risk_score; print(compute_risk_score())"`. Confirm 0-100 number with per-factor breakdown.
- Kill switch: configure with `AntiCheatProcessTrigger`, start the orchestrator, launch a known anti-cheat process — confirm `KillSwitch FIRED` log line and that all active disruptions stop.
- Diagnostics: `python -c "from app.core.diagnostics import run_all_checks; [print(r) for r in run_all_checks()]"`. Confirm 8 checks return.
- Discord webhook: paste a test webhook URL, register a `DiscordWebhookSink`, trigger any audited event — confirm the message lands in Discord with proper embed.
- Cut chaining: configure a 2-stage chain (Lag 2s → Red Disconnect 5s) against a test target. Confirm both presets fire in order with the correct gap, and the chain auto-releases the target on completion.
- OBS overlay: start the server, hit `http://127.0.0.1:4778/overlay.html` in a browser, fire a disruption, confirm the badge flips to "DISRUPTING" and shows target IP + cut state.
- Active account: cycle through tracker accounts via the hotkey (once wired), confirm `app/data/active_account.json` updates.

---

## v5.6.9 — 2026-05-12 (Engine Extensions: Preset Editor + Port + Process Scope + Backup)

Four engine extensions, all reusing existing infrastructure. None introduce new disruption capability — they expose what the engine already supports in user-controllable form, plus a one-click data-safety net.

### Added
- **Custom preset editor (`app/core/preset_store.py` + `app/gui/dialogs/preset_editor_dialog.py`).** New persistent store for user-authored presets alongside the built-in Red Disconnect / Lag / God Mode. Schema-validated (method whitelist, port-range checks, direction enum, reserved-name protection). Round-trips through JSON sidecars for sharing. Dropdown in the main view now lists built-ins first, then a divider, then sorted custom presets. The Custom Preset Editor dialog handles create / edit / delete / export / import.
- **Per-port targeting (`app/firewall/clumsy_network_disruptor.py`).** Preset params now accept `_ports: [int]` or `_ports: [{proto, port}]`. The filter builder wraps the existing target-IP clause with `(tcp.DstPort == X or tcp.SrcPort == X or udp.DstPort == X or udp.SrcPort == X)` per port atom. Lets operators scope disruption to game server ports (DayZ 2302-2305) while leaving Discord voice, browser, Steam unaffected. Empty / missing `_ports` preserves prior behavior.
- **Process-scoped disruption (`app/firewall/process_scope.py` + filter wiring).** Preset params now accept `_process_scope: "auto"` (follow foreground) or `"dayz"` (always DayZ). Builds a `(processId == NNNN or processId == MMMM)` WinDivert clause from `psutil.process_iter()` filtered to `DayZ.exe` / `DayZ_BE.exe` / `DayZ_x64.exe`. New `ProcessScopeWatcher` polls foreground state at 0.5s so auto-mode pauses cuts on alt-tab. Falls back to unscoped filter with a loud warning if no DayZ PIDs match — never silently no-ops.
- **One-click backup + restore (`app/core/backup.py`).** Bundles every persisted file (`app/data/*.json`, `*.hmac`, episode store, custom presets, audit log, config files) into a single ZIP with a manifest carrying SHA-256 per entry. Optional `--encrypt` mode wraps the ZIP with DPAPI under CurrentUser scope (same key family as the audit log and secret store). `restore_backup` verifies every entry's hash before writing; refuses path-traversal attempts; supports dry-run.

### Changed
- **Preset dropdown population (`app/gui/clumsy_control.py`).** Now driven by `_refresh_preset_dropdown()` which merges built-in PRESETS with custom presets at runtime. `PRESETS.get(name)` callsites updated to `self._presets_lookup().get(name)` so custom presets are usable in the existing handler code paths.

### Engine notes
- The four backend modules are standalone-importable and unit-testable. Self-test coverage in this release: preset validation (reserved-name rejection, bad-method rejection, port-range rejection, scope-enum rejection, export/import round-trip). Process-scope and backup modules are integration-tested manually on a Windows host since they touch OS APIs (`psutil`, `ctypes.windll.crypt32`).
- WinDivert's `processId` filter field is documented at FORWARD/FLOW layers but per-build varies on NETWORK outbound. If your driver build doesn't surface processId on the layer in use, the clause compiles but matches nothing — the engine fallback wraps the unscoped filter with the loud warning above.

### Backward compatibility
- No schema changes to built-in presets. Existing saved settings load unchanged.
- `_ports` and `_process_scope` are optional params; presets that don't set them behave exactly as v5.6.8.
- `CustomPreset` validation enforces forward-compatibility: unknown method names get rejected at save time so a future engine that drops a module can't silently break the dropdown.

### Test plan
- Open the Preset Editor (Tools menu → "Custom Preset Editor"). Create a preset named "DayZ Surgical 7s" with methods `drop` + `disconnect`, ports `2302,2303,2304,2305`, scope `auto`. Save. Confirm it appears in the main dropdown below the built-ins.
- Select it. Hit DISRUPT against an active DayZ session. Confirm the log line `[PRESET] per-port scope applied: 4 port atom(s)` and `[PRESET] process scope applied: 'auto'`.
- Verify Discord voice and browser remain unaffected during the cut.
- Tools → Backup → "Create Backup…". Save to `dupez-backup-test.zip`. Open the ZIP; confirm `manifest.json` lists every persisted file with valid SHA-256.
- Tools → Backup → "Restore Backup…" → dry-run. Confirm the preview lists every file without writing. Run for real, confirm tracker / settings / presets all survive.

---

## v5.6.8 — 2026-05-12 (Tracker Save-Bug Fix + Dupe-History Backend)

Two changes, both unblock larger features in the v6.x roadmap (`docs/ROADMAP_v6.md`).

### Fixed (data-destruction bug — high severity)
- **Account-tracker template overwriting user data on load failure (`app/gui/dayz_account_tracker.py`).** The previous load path applied the starter template (3 hardcoded rows) any time `self.accounts` came back empty, INCLUDING transient load failures: HMAC mismatch during key rotation, file corrupted in flight, brief I/O error. The template's `_apply_template` calls `account_manager.save_changes()`, which OVERWRITES the on-disk JSON with the 3 template rows. Users who imported a workbook with N accounts could launch the next day and find their data replaced. v5.6.8 distinguishes "true first launch (no data file on disk)" from "data file exists but loaded as empty" — template only seeds on the former; the latter logs an error and preserves whatever is on disk.

### Added (backend infrastructure for v5.6.9 dupe-history UI)
- **`LearningLoop.recent_episodes(limit, labeled_only)` (`app/ai/learning_loop.py`).** Returns the most recent N `EpisodeSummary` rows from the existing `app/data/episodes/*.jsonl` store. Newest-first by `start_ts`. The data substrate already existed (the EpisodeRecorder has been writing per-cut events since v5.6.0); this is the user-facing query surface so the next release can render a "Dupe History" panel without re-parsing JSONL files in the GUI thread.
- **`LearningLoop.session_summary()` (`app/ai/learning_loop.py`).** Returns aggregate counts across the entire episode store: `{total, labeled, successes, failures, success_rate, severed, degraded, never_cut, last_session_ts}`. Suitable for a dashboard header strip.

### Roadmap (informational)
- **`docs/ROADMAP_v6.md` added.** Concrete architecture + effort estimates for the six v6.x features prioritized in this cycle: dupe-history UI, hotkey macros, anti-detection telemetry, cross-game profiles, plugin marketplace, mobile companion. Recommended ordering: v5.6.9 (history UI + hotkeys) → v5.7.0 (anti-detection) → v5.7.x (cross-game) → v5.8.0 (marketplace) → v5.9.0 (mobile companion).

### Test plan
- Import a workbook, close DupeZ, reopen. The imported accounts must persist (do not get replaced by the starter template).
- Manually delete `app/data/dayz_accounts.json` while DupeZ is closed. Reopen. Template SHOULD seed (true first-launch path).
- Corrupt `app/data/dayz_accounts.json` (e.g., truncate to 0 bytes) while DupeZ is closed. Reopen. Tracker should load with no rows, log an error about preserving disk state, and NOT save the template over the corrupted file.
- `python -c "from app.ai.learning_loop import LearningLoop; print(LearningLoop().session_summary())"` should return a dict with `total >= 0` and the expected keys. Currently returns `{'total': 122, ...}` on Grihm's install.

---

## v5.6.7 — 2026-05-11 (Account-Tracker XLSX Fix + Multi-Script-Device Support)

Two operator-facing bugs in one release.

(1) The account-tracker XLSX importer silently dropped every row from workbooks where column A held the account name but the header cell above it was blank — a common spreadsheet convention (the name acts as the row label, EMAIL/STATUS/etc. start at column B). The importer's header detector happily mapped 8 columns, left column A unmapped, and then bailed on every data row because `row_data['account']` was always empty. Fixed by inferring the account column when no header maps to it but a leading unmapped column has text in the data rows. Net effect: workbooks that previously imported 0/N accounts now import N/N.

(2) The "GPC / CRONUS" panel only detected CronusZEN/MAX. Titan One and Titan Two from ConsoleTuner use the same .gpc scripting language (Cronus-derived dialect, compiled in Gtuner IV instead of Zen Studio), but their devices weren't detected and exports went to the wrong library folder. Generalized device detection to also recognize Titan VID `0x2F0A` and the legacy shared VID `0x2508`, classified by USB description string. Export-path routing now considers the detected device type and drops the script into Zen Studio for Cronus, Gtuner for Titan, with the prior Documents/DupeZ/GPC fallback for anything not classified.

### Fixed
- **Account-tracker XLSX skipping rows with blank header in column A (`app/gui/dayz_account_tracker.py`).** Auto-detection now infers an account-name column when no header maps to "account" but an unmapped column (typically column A) has consistent text content across the first few data rows. Header-row detection and the existing positional fallback are unchanged for workbooks that already worked.

### Added
- **Titan One / Titan Two detection (`app/gpc/device_bridge.py`).** New constants `TITAN_VID = "2F0A"` and `TITAN_DEVICE_NAMES`. `SUPPORTED_VIDS` tuple now contains `("2508", "2F0A")`. The Windows WMI fallback iterates supported VIDs. New `_classify_device()` helper disambiguates Cronus Zen / Cronus Max / Titan One / Titan Two from USB description + VID.
- **`ScriptDevice` dataclass (`app/gpc/device_bridge.py`).** Renamed `CronusDevice` → `ScriptDevice`; `CronusDevice` retained as a backward-compat alias so existing callers continue to import cleanly.
- **`find_gtuner_library()` + `find_cronusmax_library()` (`app/gpc/device_bridge.py`).** Locates the Gtuner IV / Gtuner II / ConsoleTuner script folders and the CronusMAX Plus library respectively, alongside the existing `find_zen_studio_library()`.
- **`get_default_export_path(device_type)` (`app/gpc/device_bridge.py`).** Routes exports based on the detected device type: Titan → Gtuner, CronusMAX → CronusMAX Plus, anything else → Zen Studio first then fallback. Backward-compatible: callers passing no argument get the pre-v5.6.7 Zen-first behavior.

### Changed
- **Panel renamed "GPC / CRONUS" → "GAME SCRIPTS" (`app/gui/panels/gpc_panel.py`).** Reflects the broader device set. Device-status banner now shows human-readable device label ("Cronus Zen", "Titan Two", etc.) instead of the raw `device_type` tag. Export dialog title updated from "GPC Export" → "Script Export".
- **Connect/disconnect callbacks (`app/gui/panels/gpc_panel.py`).** Previously inline lambdas that built a banner string and threw away the `device_type`. Now real methods that cache `self._gpc_device_type` so EXPORT routes to the correct IDE library.

### Audit notes
- Same .gpc syntax compiles cleanly on Cronus Zen Studio AND Titan Gtuner IV — the script content emitted by `gpc_generator.GPCGenerator` is unchanged, only the EXPORT target folder differs. Operators with both ecosystems installed can produce one script and run it on either device class.
- Pre-firmware-split Titan One devices that still enumerate with VID 0x2508 are caught by the shared-VID path; the description-string classifier sorts them as `titan1` so they route to Gtuner.
- Detection scope: any device exposing a Cronus or Titan USB vendor identifier OR carrying a known description substring. Adding support for additional script-device brands in the future requires only a VID entry in `SUPPORTED_VIDS` and a description-pattern in `_classify_device()`.

### Test plan
- Build with `packaging\build_variants.bat`. Confirm artifacts version 5.6.7.0.
- Import Grihm's `dayz_accounts_clean (2).xlsx`: should import 11/11 accounts (was 0/11 on v5.6.6).
- Open Game Scripts panel with no device connected: status shows "Device: None detected — scripts export to file."
- Plug in a Cronus Zen: status shows "Device: Cronus Zen — <USB description>." EXPORT writes to `Documents/Zen Studio/Library/DupeZ/<script>.gpc`.
- Plug in a Titan Two: status shows "Device: Titan Two — <USB description>." EXPORT writes to `Documents/Gtuner IV/Scripts/DupeZ/<script>.gpc`.
- Backward compat: any caller of `get_default_export_path()` (no argument) still gets the Zen-first behavior.

---

## v5.6.6 — 2026-05-11 (Auto-Update Fix: Provisioned Signing + Pipeline Integration)

The auto-updater has been fail-closed since v5.6.2 because `TRUSTED_PUBKEYS_PEM` was shipped as an empty list ("intentionally empty — causes the updater to refuse every update") and no release ever carried the `.manifest.json` / `.manifest.sig` sidecar files the verifier expects. Net effect for users: "Update failed: Update refused: signed manifest not available" toast on every check, manual download required every release.

v5.6.6 provisions the Ed25519 release keypair, embeds the pinned pubkey in `app/core/update_verify.TRUSTED_PUBKEYS_PEM`, and folds `scripts/sign-release.py` into `packaging/build_variants.bat` so the manifest + signature are emitted automatically alongside the installer on every build. Auto-update works end-to-end from v5.6.6 onward.

### Bootstrapping note for existing users
Users on v5.6.3 / v5.6.4 / v5.6.5 must perform **one manual upgrade** to v5.6.6 — their clients have no pinned pubkey and will continue to fail-closed regardless of what we ship. From v5.6.6 onward, auto-update works correctly. This is the intended security behavior: trust cannot be bootstrapped from nothing, and we will not retro-add a permissive path to old clients.

### Added
- **Ed25519 release pubkey pinned (`app/core/update_verify.py`).** `TRUSTED_PUBKEYS_PEM` now carries a single PEM-encoded Ed25519 public key. The matching private key is held offline on the maintainer's signing host. Future key rotation follows the dual-pubkey transition window documented in the module docstring.
- **Signing folded into build pipeline (`packaging/build_variants.bat`).** New step between installer build and final report: if `DUPEZ_SIGN_PRIVKEY` env var points at an existing Ed25519 PEM private key, the build invokes `python scripts/sign-release.py --sign --priv <key> --installer dist\DupeZ_Setup.exe --version <ver>`, producing `dist\DupeZ_Setup.exe.manifest.json` + `dist\DupeZ_Setup.exe.manifest.sig`. Both sidecar files are listed in the final build report and must be uploaded as release assets. Skipped gracefully if `DUPEZ_SIGN_PRIVKEY` is unset, with a clear warning that auto-update will fail-closed for clients on the resulting release.

### Changed
- **Root cleanup.** Moved `RELEASE_NOTES_v5.6.{3,4,5}.md` from the repo root into `docs/release-notes/` (which already held older release notes). Naming standardized as `vX.Y.Z.md`. Root now contains only the three top-level docs (CHANGELOG, README, ROADMAP), config files, and entry-point scripts.

### Audit notes
- The fail-closed posture has been correct since v5.6.2 — refusing every update is safer than auto-installing un-pinned code. The bug was leaving the pubkey list empty in shipped clients without surfacing that as a release blocker. v5.6.6 closes the loop.
- Private key storage on Grihm's signing host: `C:\DupeZ-keys\dupez-update-priv.pem`, ACL-locked to the signer account only. Not on PATH, not in any auto-backup target, not synced. If it leaks, follow the key-rotation procedure in `app/core/update_verify.py` docstring — generate a new keypair, ship two consecutive releases (one carrying old+new pubkeys, then one dropping the old), then sign all future releases with the new key.
- Releases v5.6.0-v5.6.5 are now "trust-orphaned" — clients on those versions cannot bootstrap into the auto-update path. This is intentional. Document in the landing page: "Users on v5.6.5 or older — please download v5.6.6 manually from the release page. Future updates will install automatically."

### Test plan
- `packaging\build_variants.bat` without `DUPEZ_SIGN_PRIVKEY` set: should build all 4 prior artifacts + skip signing with a clear warning.
- `packaging\build_variants.bat` with `$env:DUPEZ_SIGN_PRIVKEY = "C:\DupeZ-keys\dupez-update-priv.pem"`: should additionally produce `dist\DupeZ_Setup.exe.manifest.json` + `dist\DupeZ_Setup.exe.manifest.sig`. Both must be uploaded with `gh release create`.
- Manual install of v5.6.6 on a clean Win11 box, then trigger update check — should report "no newer version available" cleanly (no "signed manifest not available" toast).
- Roll a synthetic v5.6.7 release with the signed manifest, run the v5.6.6 client's update check — should download, verify, and prompt to install.

---

## v5.6.5 — 2026-05-11 (Self-Disrupt-By-Default: WiFi Lag That Actually Works)

DupeZ exists to disrupt the operator's OWN connection (typically to a DayZ server) — not to attack other devices. v5.5.0 added a WiFi same-network ARP-spoof path under the assumption that operators wanted to redirect a peer device's traffic through the operator's machine. That premise was wrong for the actual use case AND fundamentally unreliable on modern consumer WiFi (AP client isolation drops the spoof on Eero, Google Nest, most ISP gateways, all public/guest networks — see v5.6.4 honesty pass). v5.6.5 collapses the WiFi same-network path to NETWORK-layer self-disrupt by default: the operator's own packets to/from the target get the disruption treatment, which works on every AP, every encryption mode, wired or wireless, immediately, no Npcap dependency.

The v5.6.4 isolation watchdog from the in-progress design is still in the codebase as defensive infrastructure — it now only arms for power users who explicitly opt into ARP spoof via `params["_force_arp_spoof"] = True` (rare). For the default flow, self-disrupt is the day-one behavior, not a fallback.

Also folds Inno Setup compilation + the versionless installer alias into `build_variants.bat` so the release pipeline is now genuinely one command. Inno Setup deprecation warning eliminated.

### Changed (the headline)
- **`wifi_same_net` targets now use NETWORK layer / self-disrupt by default (`app/firewall/target_profile.py`).** Previously: `layer="forward"`, `needs_arp_spoof=True` → engine opens on NETWORK_FORWARD, ARP spoofer starts, hopes the AP forwards station-to-station frames. Now: `layer="local"`, `needs_arp_spoof=False` → engine opens on NETWORK layer, filters on target_ip, disrupts the operator's own egress / ingress. Works on every AP regardless of isolation, no Npcap requirement, no ARP poison.
- **`is_local` now derived from `_detection.layer` (`app/firewall/clumsy_network_disruptor.py`).** Pre-v5.6.5 `is_local` was only sourced from `params["_network_local"]`, which the controller doesn't populate from detection — so `detection.layer="local"` silently fell back to NETWORK_FORWARD. Now mapped explicitly, caller override (`params["_network_local"]`) still wins for backward compat.

### Added (infrastructure for the rare opt-in case)
- **WiFi isolation watchdog (`app/network/wifi_probe.py`).** New module with `IsolationWatchdog` class — samples `ArpSpoofer._packets_sent` vs `NativeWinDivertEngine._packets_processed` after a 5-second grace window. When sent > 0 and processed == 0, declares `ISOLATION_DETECTED` and invokes a callback. Only arms when the operator explicitly opted into ARP spoof via `_force_arp_spoof=True`. Daemon-threaded, non-blocking, cancellable. Also exposes `is_local_adapter_wifi()` for future GUI pre-flight messaging.
- **Self-disrupt auto-fallback for the ARP opt-in path (`clumsy_network_disruptor.py`).** Two new methods: `_arm_wifi_isolation_watchdog()` and `_fallback_to_self_disrupt()`. If a power user opts into ARP spoof and the spoof can't land (AP isolation), the watchdog auto-falls-back to NETWORK layer with a toast. Operator-initiated stop cancels the watchdog before teardown.
- **Inno Setup compilation folded into `packaging/build_variants.bat`.** Pipeline now runs PyInstaller → MOTW strip → ISCC → versionless alias emission in a single command. Locates ISCC.exe via PATH, then `$env:DUPEZ_ISCC`, then standard Inno Setup 6 install paths. Falls back gracefully if Inno Setup isn't installed. Closes the "iscc not on PATH + missing alias upload" gap that bit v5.6.2 → v5.6.3 → v5.6.4.

### Fixed
- **Inno Setup deprecation warning `Architecture identifier x64 is deprecated` (`packaging/installer.iss`).** Swapped `ArchitecturesAllowed=x64` and `ArchitecturesInstallIn64BitMode=x64` to `x64compatible`. Same install behavior on native x64 hosts, additionally allows install on ARM64 Windows running x64 emulation. Suppresses the ISCC 6.3+ warning.

### Audit notes
- **Self-disrupt scope is honest.** NETWORK layer captures only the operator's machine's traffic to and from the target. For DayZ duping (the canonical use case), this is exactly what's wanted: lag your own packets to the server, the server times out your character, dupe window opens. For attacking another player's session on a shared AP, no client-side approach works behind AP isolation — that requires managed-switch access upstream of the AP. v5.6.5 doesn't pretend otherwise.
- **No Npcap dependency on the default path.** Self-disrupt uses WinDivert only. Operators on stock Windows without Npcap installed now get a working WiFi disruption on day one. The v5.6.4 "Partial Failure" dialog for missing Npcap is now dead code on the default path (kept for the opt-in ARP case).
- **Watchdog is defensive infrastructure now, not a primary feature.** Self-tested in 4 scenarios (WORKING / ISOLATION_DETECTED / INCONCLUSIVE / ABORTED — all pass) but the default flow doesn't arm it.

### Test plan
- Build both variants + installer + alias in one command: `packaging\build_variants.bat`. Verify all four artifacts in `dist\`. Confirm version 5.6.5.0 in Explorer Properties.
- WiFi same-net target (Eero, public hotspot, doesn't matter): fire Red Disconnect against any reachable IP on the same /24. Expected: badge red, log shows `target {ip} on same WiFi /24 → SELF-DISRUPT mode`, engine opens on NETWORK layer, ping FROM operator TO target drops or lags as configured. No Npcap warning, no ARP toast.
- Wired Ethernet PC-LOCAL: behavior unchanged. Same NETWORK-layer path.
- Hotspot mode (PS5/Xbox on ICS): behavior unchanged. Still NETWORK_FORWARD via the explicit hotspot subnet check.
- Power-user opt-in: pass `params["_force_arp_spoof"] = True` on disrupt call. Expected: legacy v5.6.4 ARP-spoof path executes, watchdog arms, isolation auto-fallback if AP drops the spoof.
- Watchdog cancel (opt-in path only): start a `_force_arp_spoof` cut, hit STOP within 2 seconds. Expected: no watchdog callback fires.

---

## v5.6.4 — 2026-05-11 (WiFi Honesty Pass: No More Silent No-Ops)

Driven by a user report that disruption "works on Ethernet but not WiFi." Audit confirmed: when the target is on the same WiFi /24 (the `wifi_same_net` path added in v5.5.0), four failure branches in `clumsy_network_disruptor.disconnect_device_clumsy` silently degraded to "WinDivert NETWORK_FORWARD open, but no ARP spoof running" — which captures zero packets. The UI badged DISRUPTED while doing nothing. Combined with the 2026 reality that most consumer APs (Eero, Google Nest, ISP gateways, all public/guest WiFi) ship with client isolation default-on and refuse to forward station-to-station L2 frames, this looked like a randomly-broken feature when it was actually a deterministic silent failure plus an L2 attack the AP was correctly dropping.

### Fixed
- **Silent no-op when Npcap missing on WiFi same-net target (`app/firewall/clumsy_network_disruptor.py`).** Previously logged an error toast and *fell through* to open WinDivert on NETWORK_FORWARD with no spoofer running — zero packets captured, UI showed success. Now returns False so the GUI's "Partial Failure" dialog fires with install guidance.
- **Silent no-op when `ArpSpoofer.start()` fails on WiFi same-net target (same file).** Log line claimed "falling back to NETWORK layer (weak)" but the code did not actually flip `is_local` / `_network_local` back to True — it stayed on NETWORK_FORWARD with `_arp_spoofer=None`. NETWORK layer cannot affect a remote target anyway, so falling back was always a lie. Now returns False.
- **Silent no-op on `ImportError` for `arp_spoof` module (same file).** Was a toast-and-continue; now returns False.
- **Silent no-op on unexpected exception in ARP spoof startup (same file).** Was a toast-and-continue; now returns False.

### Added
- **Honest WiFi limitations section in the Help panel (`app/gui/panels/help_panel.py`).** Documents the three real reasons WiFi peer-targeting fails on modern consumer routers (AP client isolation, wireless L2 model, the v5.6.4 honesty fix itself) and clarifies that WinDivert-only PC-LOCAL modes work identically wired and WiFi.

### Audit findings (informational — no code change shipped)
- Eero (main + guest), Google Nest Wifi, and most ISP gateways have AP client isolation default-on with no user toggle. ARP spoof against a peer on these networks will reach the AP and stop there. There is no honest fix from the client side.
- WinDivert binds at the WFP layer above the NIC and is adapter-agnostic — works identically on wired and 802.11. The failure mode is the *targeting* layer (ARP), not WinDivert itself.
- Npcap monitor mode + injection for deauth-class attacks remains gated to a tiny set of chipsets in 2026 (Intel AX200/AX210 still fails per nmap/npcap#639); not shippable in a consumer tool.
- WPA3 + 802.11w MFP enforcement is still <10% of consumer auths globally as of Feb 2026, but doesn't matter — consumer APs already drop client-to-client L2 traffic by other means.
- **Planned for v5.6.5:** WiFi-aware pre-flight probe (`is_local_adapter_wifi()` via `GetIfTable2`, `probe_ap_isolation()` via warmup ARP + ICMP roundtrip), self-disrupt fallback mode when AP isolation is detected.

### Test plan
- Build both variants: `packaging\build_variants.bat`. Verify `dist\DupeZ-GPU.exe` and `dist\DupeZ-Compat.exe` show version 5.6.4.0.
- WiFi same-net target with Npcap **uninstalled**: fire Red Disconnect. Expected: "Partial Failure" dialog appears, log shows `[WiFi] Cannot ARP-spoof: ... Aborting disruption`. Previously: badge turned red, no packets intercepted.
- WiFi same-net target on a router with AP client isolation ON, Npcap **installed**: fire Red Disconnect. Expected: ArpSpoofer starts, but if the spoof can't land, target is unaffected. (Detection of isolation arrives in v5.6.5; v5.6.4 stops lying about the *cause* of silent failure but cannot yet detect AP isolation itself.)
- Wired Ethernet, same target as previous test: behaviour unchanged. Disruption lands.
- PC-LOCAL mode (target = own machine's connection to remote game server) over WiFi: behaviour unchanged. WinDivert intercepts local egress identically to wired.

---

## v5.6.3 — 2026-04-19 (Crash-Safety + Duping Audit Hardening)

Tightens the process-level crash-safety story across the full launch path. Driven by a deep audit of the duping subsystem (Red Disconnect / clumsy / netcut-style ARP) that confirmed the hot path is solid — but found three latent failure modes around C-extension crashes, helper death recovery, and split-mode shutdown. Also fixes documentation drift and a dead taskkill in the build script.

### Added
- **`faulthandler` enabled at process entry (`dupez.py`).** Installs a signal handler that dumps a Python-level stack to stderr from the C crash path. `sys.excepthook` only catches Python exceptions; when WinDivert.dll, Qt6Core.dll, or Chromium's GPU process segfaults, the process previously died with no traceback at all. Now the crash leaves a usable trace.

### Fixed
- **Pipe-disconnect stuck state in `DisruptionManagerProxy._call` (`app/firewall_helper/ipc_client.py`).** When the elevated helper crashed mid-session, the proxy's `_connected` flag stayed True forever — every subsequent `disrupt_device()` call returned False silently with no recovery path. `_call` now catches `(ConnectionError, OSError, BrokenPipeError)`, closes the dead client, resets `_connected=False` and `_helper_spawn_attempted=False`, then re-raises so the next call re-spawns the helper cleanly.
- **`_shutdown_cleanup` bypassed the feature-flag factory (`app/main.py`).** Imported `disruption_manager` directly, which under `DUPEZ_ARCH=split` is the in-process singleton — *not* the real engine running in the elevated helper. Result: split-mode shutdown was a silent no-op and could leave packet filters live across app restarts. Now uses `get_disruption_manager()` so split mode tears down via IPC; inproc behaviour unchanged.
- **Stale "95% drop" doc in Red Disconnect help (`app/gui/panels/help_panel.py`).** Two locations referenced the legacy 95% drop value; the actual preset has shipped at 100% drop since the disconnect-module rewrite. Updated to match runtime behavior.
- **Dead `taskkill /f /im dupez_helper.exe` in build script (`packaging/build_variants.bat`).** No separate helper exe is built — the elevated helper is `DupeZ-GPU.exe` re-invoked with `--role helper`. Removed the no-op kill and replaced with a clarifying comment so future maintainers don't reintroduce a separate helper binary by mistake.

### Test plan
- Build both variants: `packaging\build_variants.bat`. Verify `dist\DupeZ-GPU.exe` and `dist\DupeZ-Compat.exe` are produced and version stamp shows 5.6.3.0.
- Smoke-launch GPU variant on a Win11 box with a discrete GPU. Confirm Medium-IL launch, helper spawns on first DISRUPT, Red Disconnect lands.
- Smoke-launch Compat variant on a Win10 box with no GPU. Confirm self-elevation, inproc engine starts.
- Force a helper kill mid-disruption: `taskkill /f /im DupeZ-GPU.exe` against the elevated child. Next DISRUPT click should re-spawn the helper, not fail silently.
- Verify FATAL_CRASH.txt contains a scrubbed traceback if you induce a hard crash via debug menu.

---

## v5.6.2 — 2026-04-17 (Nation-State Hardening: §9.2 Second-Factor + Signed Auto-Update + Tracker Fixes)

Closes the last open blocker on the nation-state certification track (§9.2 strong second-factor authentication) and fail-closes the auto-updater behind a pinned Ed25519 signing chain. Also unblocks a long-standing DayZ account-tracker import regression where Excel-exported CSVs silently dropped every row, plus housekeeping for the offsec CLI stdout/stderr split. Verdict per `docs/release-notes/CERTIFICATION_v5.6.2.md`: **CERTIFIED — Nation-State Grade**.

### Added
- **§9.2 second-factor authentication gate (`app/core/second_factor.py`).** SP 800-63B / CNSA 2.0-aligned WebAuthn / FIDO2 / TOTP scaffold. RFC 6238 TOTP with HMAC-SHA256 (not SHA-1), 256-bit seeds, ±1-step skew window. Constant-time compare via `hmac.compare_digest`. Sliding-window rate limiter (5 failures / 15 min, lockout). Process-wide singleton with thread lock. Scope allowlist (`elevation`, `plugin_install`, `offsec.engagement`, `secret_rotation`, `self_test`) — unregistered scopes raise. FIDO2 provider gracefully reports `available=False` when `python-fido2` is absent and **never** silently passes. Cache TTL with `bypass_cache` override. CI bypass via `DUPEZ_SECOND_FACTOR_DISABLED=1`.
- **Gate wired into elevation, plugin loader, and offsec runner.** `app/firewall_helper/elevation.py` calls `gate.require("elevation", …)` before spawning the firewall helper. `app/plugins/loader.py` calls `_enforce_second_factor("plugin_install", …)` from both `load_all()` and `load_plugin()`. `app/offsec/runner.py` calls the gate after consent check and before tactic dispatch with scope `offsec.engagement`.
- **Signed auto-update verification (`app/core/update_verify.py`).** Pinned Ed25519 release-key chain with `TRUSTED_PUBKEYS_PEM` allowlist (currently empty → updater is **fail-closed** until first key provisioning). Manifest schema `dupez.update-manifest.v1` with version, released_at, installer filename, SHA-256 hex, and size. Detached 72-byte signature envelope: 8-byte SHA-256 pubkey fingerprint + 64-byte Ed25519 signature. Manifest size cap (64 KB), installer size cap (1 GB), filename anti-traversal check. Updater (`app/core/updater.py`) refuses to launch any installer whose manifest fingerprint, signature, schema, version, filename, size, or SHA-256 don't all verify. Phase-2 stream download enforces signed `installer_size` as a hard byte cap before hash check.
- **`scripts/sign-release.py` offline signing tool.** Generates Ed25519 keypairs, builds canonical-JSON manifest, signs and round-trip self-verifies. Designed to run on an air-gapped host or HSM. CLI: `--gen-key`, `--sign`, `--verify`. Documented key-rotation flow in module docstring.
- **`tests/test_second_factor.py`.** 13 tests against the §9.2 gate via in-memory `secret_store` fixture (works on any OS, no DPAPI). Audit-logger stub prevents pytest pollution of production audit chain at `app/data/audit.jsonl`. Covers TOTP enroll/verify, skew window, non-digit input rejection, scope registry enforcement, prompter cache short-circuit, rate-lockout, revocation, FIDO2 graceful unavailability, and re-enrollment seed rotation.
- **`tests/test_account_tracker_csv.py`.** 25 regression tests over the DayZ account tracker CSV/XLSX import path. AST-based loader extracts non-Qt helpers without spinning up the GUI graph. Covers BOM stripping, tag-prefix stripping (`#`, `@`, `:`), separator collapsing (`-`/`_`/`.`), header synonym map (15+ aliases), status/station case canonicalization, and the `_XLSX_DEFAULT_FIELDS == ACCOUNT_FIELDS` off-by-one guard.
- **`.github/workflows/tests-ci.yml`.** Windows-runner pytest matrix (Python 3.11 + 3.12) with coverage on `app.core.second_factor` and `app.gui.dayz_account_tracker`. Sets `DUPEZ_OFFSEC_CONSENT=""` and `DUPEZ_SECOND_FACTOR_DISABLED=1` so gated surfaces don't stall on prompts. Second job `ast-lint` AST-parses every `app/**/*.py` on Ubuntu — fails the PR on any syntax error.

### Fixed
- **DayZ account tracker CSV/XLSX import dropped every row from Excel-exported files.** Four cumulative root causes in `app/gui/dayz_account_tracker.py`:
  1. `_XLSX_DEFAULT_FIELDS` was missing the `value` column → positional mapping was off-by-one for headerless files.
  2. `encoding='utf-8'` did not strip the UTF-8 BOM Excel adds → first header was un-mappable → every row was silently dropped.
  3. Header-synonym map was thin: `character`, `server`, `kit`, `role`, `inv`, `tier` and tag-prefixed forms (`#email`, `@notes`, `:notes`) were not recognised.
  4. No delimiter sniffing → semicolon- and tab-delimited CSVs were parsed as a single-column table.
  Now: `utf-8-sig` decoding, `csv.Sniffer` for delimiter, expanded synonym map, full ACCOUNT_FIELDS in defaults. Regression tests in `tests/test_account_tracker_csv.py`.
- **Offsec CLI stdout pollution by INFO logger (Task #19).** `app/logs/logger.py` now routes INFO chatter to stderr when `DUPEZ_OFFSEC_CLI=1` or `offsec` appears in `sys.argv[:3]`, so callers consuming machine-parseable JSON on stdout don't get logger noise mixed in. Warnings/errors always go to stderr regardless.
- **`packaging/version_info.py` PE resource version drift.** `filevers`/`prodvers` tuples were stuck at `(5, 6, 0, 0)` while string fields advanced to `5.6.1.0`. Now `(5, 6, 2, 0)` and `5.6.2.0` aligned.

### Changed
- **Root directory cleaned for v5.6.2 release.** Superseded audit/cert artifacts moved to `docs/archive/2026-04-17/` (`MASTER_CERTIFICATION_2026-04-17.md`, `_v2.md`, `SECURITY_AUDIT_2026-04-17_v2.md`, `SECURITY_CERTIFICATION.md`, `COMPLEXITY_AUDIT_2026-04-17.md`, `AUDIT_2026-04-17.md`, `ROADMAP_2026-04-17.md`). v3 master cert promoted to `docs/release-notes/CERTIFICATION_v5.6.2.md` as the shipping cert. Intermediate `requirements-locked.txt.body` and `requirements-locked.txt.generated` artifacts archived (already in .gitignore).
- **All version strings bumped to 5.6.2.** `app/__version__.py`, `packaging/version_info.py`, `packaging/build.bat`, `packaging/build_variants.bat`, `packaging/dupez.manifest`, `packaging/dupez_compat.manifest`, `packaging/installer.iss`, `README.md`.

### Security
- **Auto-update is fail-closed until release-key provisioning.** `TRUSTED_PUBKEYS_PEM` is intentionally empty in this client — the updater refuses every signed update and falls through to opening the GitHub release page in the user's browser. To enable signed in-app updates: generate a keypair offline (`scripts/sign-release.py --gen-key`), paste the pubkey PEM into `TRUSTED_PUBKEYS_PEM`, ship a client release carrying the new pubkey, then sign subsequent installers with the matching private key. Documented rotation flow in `app/core/update_verify.py` and `scripts/sign-release.py` module docstrings.
- **Compromise of GitHub no longer translates 1:1 to silent installer-grade RCE.** Pre-v5.6.2, an attacker with write access to GrihmLord/DupeZ releases could swap the `DupeZ_Setup.exe` asset and every auto-updater client would silently install it. With the signed-manifest chain in place, that swap requires *also* compromising the offline-held private key matching one of the pinned pubkeys.

### Test plan
- `pytest tests/test_second_factor.py -v` — 13 pass on Linux+Windows (in-memory secret_store shim).
- `pytest tests/test_account_tracker_csv.py -v` — 25 pass via AST helper extraction (no Qt required).
- AST-lint over `app/**/*.py` — all files parse cleanly.
- Offsec engagement on Windows host (DPAPI + WinDivert + named pipes): 1 HIGH / 14 MEDIUM / 3 LOW / 8 INFO. Net **−1 HIGH** vs v2 baseline; 0 new findings. Remaining HIGH (`DUPEZ-OFFSEC-0022`) is the standing architectural finding for which §9.2 is the countermeasure.

---

## v5.6.1 � 2026-04-15 (Updater Stability)

### Fixed
- **Updater no longer spuriously prompts when already on latest.** Added equal-tag short-circuit in `UpdateChecker.check_sync` � if normalized current and latest tags match exactly, `is_newer` is False without falling through to numeric compare. Guards against stale frozen `__version__` values causing re-prompts.
- **Installer URL now uses stable versionless alias.** `installer_url` is set to `https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe` regardless of what the GitHub API asset scan resolved. Same stable URL the landing page CTA uses � self-updating per release.

### Changed
- Packaging manifest versions (`dupez.manifest`, `dupez_compat.manifest`) bumped from stale `5.5.0.0` to `5.6.1.0` to match runtime.

---
## v5.6.0 — 2026-04-14 (MAC-Spoof Spike + A2S Cut Verification + Learning-Loop Closure)

Three-frontier release that closes the observability loop on cut effectiveness, hardens the ARP-poison path against consumer-router anti-spoof heuristics, and fills in the vendor column for every IEEE-registered OUI. The disruption pipeline now produces labeled episodes end-to-end with no operator input required.

### Added
- **MAC-spoof spike in `arp_spoof.py`.** Gateway-facing poison frames now ship in three variants per cycle: opcode-2 reply with L2 source set to the *target's* MAC (defeats ASUS/Netgear/Ubiquiti anti-spoof heuristics that pin ARP sender MAC to the frame source MAC), plus an opcode-1 request variant for RFC 826 strict-mode routers that ignore unsolicited replies. Target-facing frames unchanged.
- **A2S cut verifier → episode recorder.** `CutVerifier` subscriber inside `NativeDivertEngine` now writes a `cut_verified` event every time the verdict state transitions (unknown → connected → degraded → severed). `engine_stop` payload carries `max_cut_state` so post-session aggregation sees the peak severance reached.
- **`LearningLoop.cut_effectiveness(profile, goal)`.** New aggregation method distinct from `recommend()` — measures whether the cut even *fired correctly* (severance), not whether the dupe stuck. Returns `{n, severed_rate, degraded_rate, never_cut_rate, sufficient_data}`. Lets the auto-tuner pick a different preset when the current one can't sever this target class at all.
- **`EpisodeSummary.max_cut_state` field.** Parsed from `cut_verified` events and `engine_stop.max_cut_state` in `_summarize_episode`, with strict state-order tracking (`unknown < connected < degraded < severed`) so the peak is stable across restarts.
- **Full scapy MANUFDB fallback in `app/network/shared.py`.** `lookup_vendor()` now lazy-loads `scapy.data.MANUFDB` (~35k IEEE OUI entries) on first miss in the curated 60-entry `VENDOR_OUIS` table. Device table vendor column now resolves Ring, HUMAX, Murata, Texas Instruments, Chamberlain, HP, and every other registered manufacturer instead of showing "Unknown".
- **`tools/smoketest_scan_and_lag.py`.** End-to-end pipeline validator: scan → pick target (by last octet or first console) → start lag via `disruption_manager.disrupt_device` → poll engine stats for N seconds → stop. Exit codes distinguish scan-empty, target-not-resolvable, disrupt-returned-false, and zero-packet-processed cases. Vendor column rendered in device table output.

### Changed
- **`help_panel.py` Getting Started.** New "🛡 ARP SPOOF & A2S CUT VERIFIER" section covering MAC-spoof spike rationale, A2S baseline / drop detection, and what `max_cut_state` means in session logs.
- **`ArpSpoofer._poison_once`** now emits three gateway-facing frames per cycle instead of one. Target-facing path unchanged.
- **Smart Mode panel surfaces historical severance.** `SmartModePanel.update_ui` queries `LearningLoop.cut_effectiveness(profile, goal)` after every profile and renders a colour-coded hint line below the recommendation: severance rate, sample size, and a tier label (`great`/`ok`/`weak`/`nodata`). Auto-tuner now has a visible rationale for preset switching.
- **Live cut-state LED in the Stats panel banner.** `StatsPanel` prepends a coloured dot to every active device's banner line (gray=unknown, green=connected, amber=degraded, red=severed) with matching text colour on the `CUT:` fragment. Rich-text rendering enabled (`Qt.TextFormat.RichText`).
- **Pytest hardware marker + opt-in smoketest.** New `tests/test_hardware_smoketest.py` mirrors `tools/smoketest_scan_and_lag.py` as pytest assertions. Gated behind `@pytest.mark.hardware` so default `pytest` excludes it; opt in with `pytest -m hardware` on a Windows Admin host with WinDivert + Npcap. Prerequisite probes skip with specific reasons when the environment doesn't match. `pytest.ini` registers the `hardware` and `slow` markers with `--strict-markers`.

### Fixed
- **Vendor column stuck at "Unknown".** Root cause: curated `VENDOR_OUIS` only covered ~60 gaming-focused OUIs. Fixed via scapy MANUFDB chain fallthrough.
- **Strict-mode routers ignoring poison.** Opcode-1 (request) variant bypasses RFC 826 "unsolicited replies are invalid" enforcement seen on newer ASUS firmware.
- **Labeled episodes stuck at 0.** `LearningLoop.recommend()` required ≥5 labeled episodes per bucket but no code path was producing outcome labels without operator intervention. `cut_end` now auto-labels from `persisted` flag on the engine stop path, unblocking SMART DISRUPT recommendations after 5 cuts.
- **Auto-preset-switch dead-code bug.** `SmartDisruptionEngine._maybe_switch_preset_by_severance` used `getattr(dict_result, "sufficient_data", False)` — attribute access on a dict always returns the default, so the gate never opened and the feature never fired. Replaced all `getattr()` calls with `.get()`. Feature is now live.

### Performance
- **`LearningLoop` bucket indexing.** `recommend()` and `cut_effectiveness()` previously rebuilt a full-cache filter list comprehension on every call (O(n) per query, O(n) allocation). Added `_index_labeled` and `_index_all: Dict[(target_profile, goal), List[EpisodeSummary]]` built once per disk-refresh in `_rebuild_indices()`. Query path is now O(1) bucket lookup. Matters because `SmartModePanel.update_ui` calls `cut_effectiveness` on every Qt refresh tick.
- **`cut_effectiveness` single-pass counting.** Collapsed three independent `sum(1 for e in rows if …)` generators into one for-loop with three counters. Same asymptotic class, 3× fewer traversals, zero generator-expression object allocations.
- **`SmartDisruptionEngine` duplication + I/O.** Collapsed `recommend()` and the duplicated `_recommend_without_switch()` into a single `_build_recommendation(auto_switch_enabled: bool)`. Cached the `LearningLoop` instance on `self._learning_loop` to eliminate per-call disk reads of `cut_history.json`.

### Repo hygiene
- **Root directory cleanup.** Moved `DEPLOY_CHECKLIST_v5.4.0.md` → `docs/release-notes/`, `DupeZ_Deep_Research_and_DL_Plan.docx` → `docs/`, and `FATAL_CRASH.txt` → `logs/archive/FATAL_CRASH_2026-04-14.txt`. Root is now limited to standard top-level entries: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `requirements*.txt`, `pytest.ini`, and the two entry-point scripts (`dupez.py`, `dupez_helper.py`).

---

## v5.5.0 — 2026-04-12 (WiFi ARP Spoof + Codebase Audit Cleanup)

Feature release adding WiFi same-network interception via ARP cache poisoning and cleaning up technical debt identified during the Phase C principal-engineer codebase audit.

### Added
- **WiFi same-network interception.** New `wifi_same_net` connection mode in `target_profile.py`. When DupeZ detects the target is on the same WiFi network (not behind the hotspot), it automatically enables ARP spoofing to intercept traffic via `arp_spoof.py`.
- **`app/gui/widgets/` package.** Extracted `CollapsibleCard` into a shared reusable widget module so any panel can use it without importing `clumsy_control.py`.

### Removed
- **Dupe Engine v1 (`dupe_engine.py`).** Deprecated since 5.4.0. The `DupeMethod.LEGACY` mode in v2 is self-contained and handles pre-1.29 servers without the v1 module. The DayZ inventory mechanics docstring was preserved in v2's module docstring.
- **`dupe_v1` module registry key.** Removed from `CORE_MODULE_MAP`.

### Changed
- **`ml_classifier.py` PRNG refactored.** Replaced module-level mutable `_rng_state = [42]` list with an `_LCG` class holding state on the instance. Thread-safe by design.
- **`packet_classifier.py` type fix.** `_finalize_calibration` return type corrected from `Optional[Any]` to `None`.
- **`CollapsibleCard` now supports style overrides.** New `header_qss` and `reorder_qss` constructor params, plus `set_expanded()` public API.

---

## v5.4.0 — 2026-04-12 (Account Tracker Overhaul + UI Polish + Bug Fixes)

Feature release focused on the Account Tracker, theme stability, and overall UI polish. The tracker is now a full-featured multi-account management tool with multi-select, context menus, status filter chips, notes, and improved bulk operations. Six bugs from v5.3.0 are fixed, and the Help panel and About dialog have been rewritten.

### Added
- **Account Tracker: Notes field.** New per-account `notes` column for private reminders, coordinates, or anything else. Stored, exported, and imported alongside all other fields.
- **Account Tracker: Multi-select.** Ctrl+click and Shift+click to select multiple rows. Delete and status changes work on multi-selected rows.
- **Account Tracker: Right-click context menu.** Edit, Duplicate, Set Status (submenu), and Delete — directly from the table. Works on single or multi-selected rows.
- **Account Tracker: Quick-filter status chips.** One-click toggle buttons above the table to filter by Ready, Dead, Storage, Blood Infection, or Offline. Combines with the search bar.
- **Account Tracker: Duplicate account.** Clone any account with auto-incrementing "(copy)" suffix.
- **Account Tracker: Row numbering.** `#` column at position 0 for easy reference.
- **Account Tracker: Last modified display.** Selecting an account shows its last-modified timestamp in the status bar.
- **Account Tracker: Editable dropdowns.** Status and Station combos accept custom values beyond the preset list.
- **Account Tracker: Upgraded bulk operations.** Scope by All / Selected / Filtered-by-Status. Operations: Change Status, Set Location, Clear Notes, Delete, Export Matching.
- **Account Tracker: Export subset.** Bulk ops can export only the matching accounts to XLSX or CSV.
- **GPU auto-detection fallback** in `feature_flag.py`. If no env var or compiled default is set, `get_arch()` probes for a discrete GPU and selects `split` or `inproc` accordingly.
- **About dialog: ARCH row.** Dynamically displays whether the running build is Split or In-process.

### Changed
- **About dialog rewritten.** Broader tagline (no longer DayZ-specific), ARCH info row, condensed credits, "View on GitHub" + "Close" button pair, subtle cyan separators.
- **Help panel rewritten.** All 11 sections updated with accurate content matching the actual codebase — keyboard shortcuts, troubleshooting messages, feature descriptions.
- **Account dialog styled.** Dark-themed `_DIALOG_QSS`, better placeholder text, multi-line Notes input.
- **Nav button layout hardened.** `_NAV_BTN_QSS` with explicit fixed 40×40 dimensions, `setObjectName("nav_btn")`, and `_reapply_nav_styles()` called after every theme switch.
- **Rainbow theme auto-starts.** `apply_theme("rainbow")` now calls `_ensure_rainbow_timer()` so the animation begins immediately.
- **Theme QSS files updated.** All four themes (dark, light, hacker, rainbow) include `QPushButton#nav_btn` rules with fixed dimensions.

### Fixed
- **"Engine unavailable no admin" status bar message.** `_BUILD_DEFAULT_ARCH` was `'inproc'` in the GPU variant; changed to `'split'`.
- **Map slow despite GPU.** Same root cause — split arch wasn't defaulting correctly; GPU auto-detect fallback added.
- **Theme switching breaks sidebar button layout.** App-level `QPushButton` stylesheet selectors were overriding widget-level inline styles. Fixed with `#nav_btn` object name and explicit re-application after theme change.
- **Rainbow theme doesn't animate.** `apply_theme("rainbow")` loaded the static QSS but never started the animation timer. Now auto-starts.
- **Overlapping sections in Clumsy Control.** Increased section spacing from 4px to 8px, added content margins.
- **Settings dialog: return type annotation typo.** `_read_widgets_to_dict -> d` corrected to `-> dict`.
- **Account Tracker: duplicate imports.** `_try_import_account` was appending to both `self.accounts` and `account_manager.accounts`. Now only appends to manager; local list refreshed after batch.
- **Account Tracker: signal stacking.** `itemSelectionChanged.connect()` called every rebuild without disconnecting. Fixed with try/except disconnect-before-reconnect.
- **Account Tracker: reference-sharing mutation.** `self.accounts = account_manager.accounts` shared the same list object. All assignments now use `.copy()`.

---

## v5.3.0 — 2026-04-11 (Split-Elevation Architecture + Hardware Map + Preset Collapse)

Minor release landing the ADR-0001 split-elevation architecture end-to-end, collapsing the preset taxonomy from 8 entries to 5, reorganizing packaging files into a dedicated `packaging/` subtree, beefing up hostname resolution in the scanner, and bundling zeroconf for real mDNS discovery. This is the first DupeZ release that ships **two user-facing binaries** from one codebase: `DupeZ-GPU.exe` (asInvoker, split-arch, hardware-rasterized map) and `DupeZ-Compat.exe` (requireAdministrator, legacy inproc, CPU-raster fallback).

### Added
- **`DupeZ-GPU.exe` + `DupeZ-Compat.exe` dual-variant builds.** `packaging/build_variants.bat` is the new canonical release driver. Both specs share `packaging/build_common.py`, which writes a per-variant `app/firewall_helper/_build_default.py` before Analysis so the compiled-in `DUPEZ_ARCH` default (`split` for GPU, `inproc` for Compat) is baked in at freeze time. No env var required at runtime. See ADR-0001 §11.
- **Split-elevation helper process (`dupez_helper.py`) reachable via helper-role dispatch.** Under `DUPEZ_ARCH=split`, the elevated helper is the same frozen exe re-invoked with `--role helper --parent-pid N`. The dispatch runs before any `app.*` / PyQt6 import so the helper never boots the GUI, which previously caused an infinite admin-spawn loop.
- **Hardware raster tier resolver (`app/gui/map_host/renderer_tier.py`).** Picks tier1_hw / tier2_swiftshader / tier3_cpu based on `DUPEZ_MAP_RENDERER` and a best-effort GPU probe, then applies the matching `QTWEBENGINE_CHROMIUM_FLAGS` before any PyQt6 import. Under split mode, the embedded iZurvive map runs GPU-accelerated for the first time. The "Open in Browser ↗" escape hatch tooltip now reports which tier is active.
- **Multi-stage hostname resolution chain in `app/network/enhanced_scanner.py`.** Order: `gethostbyaddr` → `getfqdn` → NetBIOS (`nbtstat -a`) → mDNS (zeroconf) → synthesized (`<vendor>-<mac_suffix>` or `device-<ip>`). The GUI Hostname column is never blank or "Unknown" again. `app/network/device_scan.py` and `app/core/state.py` now also defensively synthesize on input dicts that arrive with missing hostnames.
- **`zeroconf>=0.130.0` added to `requirements.txt`** and hiddenimports so mDNS discovery works out of the box in frozen builds. Previously soft-imported and silently skipped even when installed in dev.
- **`packaging/` subtree.** All build artifacts (`build.bat`, `build_variants.bat`, `build_common.py`, `dupez.spec`, `dupez_gpu.spec`, `dupez_compat.spec`, `dupez.manifest`, `dupez_compat.manifest`, `installer.iss`, `version_info.py`) now live under `packaging/`. Spec files use `HERE = os.path.dirname(SPEC)` + `ROOT = HERE/..` to resolve paths correctly from the subdirectory. Inno Setup uses `SourceDir=..` to keep the existing `Source:` path layout working unchanged.
- **ADR-0001 compat shim for legacy inproc mode.** On `DUPEZ-Compat.exe`, if the launcher detects non-admin + inproc, it self-elevates via `ShellExecuteW runas` before any Qt import. UAC decline (ERROR_CANCELLED 1223) surfaces a readable stderr message instead of silent exit.

### Changed
- **Preset taxonomy collapsed 8 → 5.** `app/gui/clumsy_control.py`'s `PRESETS` dict now ships only `Red Disconnect`, `Lag`, `God Mode`, `Dupe Mode`, `Custom`. Removed: `Heavy Lag`, `Light Lag` (merged into `Lag` — tune via the Lag Delay / Drop % sliders; Light ≈ 800ms/60%, Heavy ≈ 3000ms/95%), `God Mode Aggressive` (redundant with sliders), `Desync` (rarely used, covered by Custom).
- **`app/firewall/blocker.py` routes through the helper under split mode.** `block_device`, `unblock_device`, `is_ip_blocked`, `clear_all_dupez_blocks`, `get_blocked_ips` all check `is_split_mode()` first and forward to `get_proxy_manager()` IPC when split. Inproc path is untouched.
- **`app/core/controller.py` obtains `disruption_manager` via `get_disruption_manager()` factory** instead of direct import. Under inproc, returns the same singleton (zero behavioural change). Under split, returns the IPC proxy. Fully transparent to downstream code.
- **`app/gui/splash.py` defers WinDivert engine check under split mode.** Previously polluted the splash log with scary red "WinDivert engine: unavailable" lines because the GUI at Medium IL can't initialize the DLL. Now reports `WinDivert engine: deferred (split mode — helper owns engine)` and moves on.
- **`AA_ShareOpenGLContexts` application attribute** now set on `QCoreApplication` before `QApplication` instantiation in `app/main.py`. Qt 6 requires this for WebEngine + any OpenGL-adjacent widget to coexist on the same thread.
- **Manifest execution level flipped to `asInvoker`** on `dupez.manifest` and `dupez_compat.manifest`. See compat shim note above — `Compat` variant still self-elevates at startup, so end-user experience is unchanged there.
- **Build pipeline runs from repo root** regardless of where the `.bat` lives. Both `build.bat` and `build_variants.bat` now `pushd "%~dp0.."` at the top and use explicit `packaging\<spec>.spec` paths.
- **README project tree + build section** updated for the new `packaging/` layout and dual-variant commands.
- **`app/__version__.py` lockstep docstring** updated to reference the new `packaging/` paths.

### Fixed
- **Infinite admin-spawn loop** when `DupeZ-GPU.exe --role helper` re-launched the GUI instead of dispatching to the helper module. Root cause: `_maybe_dispatch_helper_role()` ran too late. Fixed by dispatching at the top of `dupez.py` before any other import.
- **Chromium GPU init deadlock under admin token** (legacy inproc). Pre-existing workaround (`--no-sandbox --disable-gpu`) now only applied when the tier resolver reports `tier3_cpu`; split mode gets real hardware raster.
- **`plugins/example_ping_monitor/plugin.py`** missing `typing.Any` import (was `from typing import Dict` only, but used `Dict[str, Any]`).
- **`packaging/build.bat` final line truncation** (pre-existing). Was cut off mid-word at `set DUPEZ_SIGN_CE` with no newline, no `popd`, no `endlocal`, no `pause`. Fixed.

### Packaging / Repo Hygiene
- Root cleanup: deleted `FATAL_CRASH.txt`, `crash-trace.txt`, `launch_error.txt`, stray `query` file, `__pycache__/`, `.pytest_cache/`. `.gitignore` now covers the transient crash-dump patterns so they don't sneak back in.
- `packaging/installer.iss` gains `SourceDir=..` so all existing `Source:` paths resolve from repo root despite the `.iss` file living in `packaging/`.

### Migration Notes
- **Two binaries now ship per release.** `DupeZ-GPU.exe` is the recommended default and gives the smoothest map experience. `DupeZ-Compat.exe` is the fallback for machines where split-mode IPC or WebEngine hardware raster misbehaves. Installer bundles both.
- **Preset UI shows 5 entries instead of 8** — if you had muscle memory for `Heavy Lag` / `Light Lag` / `God Mode Aggressive` / `Desync`, the equivalents are: `Lag` (with sliders for intensity), `God Mode` (with sliders), or `Custom`.
- **No settings file migration required.** `%APPDATA%\DupeZ` schema is unchanged from v5.2.4.
- **zeroconf is now a hard requirement** for `pip install -r requirements.txt`. If you pin dependencies in a virtualenv, `pip install zeroconf` is the only new line.

---

## v5.2.4 — 2026-04-10 (Installer Architecture Fix + Manifest Sync)

Patch release fixing a latent installer misconfiguration where a 64-bit binary was being installed into the 32-bit `C:\Program Files (x86)` path, and bringing the Windows side-by-side manifest in sync with the release version.

### Fixed
- **Installer now lands in `C:\Program Files\DupeZ`** on 64-bit Windows (previously `C:\Program Files (x86)\DupeZ`). Root cause: `installer.iss` had no `ArchitecturesInstallIn64BitMode` directive, so Inno Setup defaulted to 32-bit install mode and resolved `{autopf}` to the x86 Program Files path. The bundled `dupez.exe` has been 64-bit since v5.2.0, so this was wrong from day one of the installer pipeline. Added `ArchitecturesInstallIn64BitMode=x64` and `ArchitecturesAllowed=x64`. The 64-bit registry hive is now used for uninstall entries, and Add/Remove Programs reports the architecture correctly.
- **`dupez.manifest` `assemblyIdentity` version now matches the release.** It was stuck at `5.2.0.0` across every v5.2.x patch because the manifest wasn't in the per-release bump checklist. Now tracked in `app/__version__.py`'s docstring so it won't drift again.

### Changed
- **`app/__version__.py` docstring** now lists `dupez.manifest` and `ROADMAP.md` alongside `version_info.py`, `installer.iss`, `build.bat`, `README.md`, and `CHANGELOG.md` as files that must be bumped in lockstep each release.
- **`ROADMAP.md` Completed section** now reflects v5.2.1, v5.2.2, v5.2.3, and v5.2.4 shipping dates and summaries. Previously only v5.2.0 was listed.

### Migration Notes
- **Existing v5.2.0–v5.2.3 installs living in `C:\Program Files (x86)\DupeZ`:** the v5.2.4 installer will NOT upgrade them in place because the install path moved. Uninstall the old version from Add/Remove Programs first, then install v5.2.4. Your user settings in `%APPDATA%\DupeZ` are preserved across uninstall/reinstall.
- **No functional changes** to network, map, voice, firewall, or auto-updater paths. Pure packaging fix.

---

## v5.2.3 — 2026-04-10 (Version Display Fix + Single Source of Truth)

Patch release fixing a latent bug where the dashboard title bar and HTTP `User-Agent` header still reported `5.2.0` regardless of the actual build version. The PyInstaller `VS_VERSION_INFO` resource on the .exe was correct (Windows Properties dialog showed 5.2.2), but the in-app title was hardcoded.

### Fixed
- **Dashboard title bar now reports the actual build version.** Root cause: `app/core/updater.py` hardcoded `CURRENT_VERSION = "5.2.0"`, and `app/gui/dashboard.py` read from it for the window title. Fixed by pointing `CURRENT_VERSION` at a single source of truth.
- **HTTP `User-Agent` header now reports the actual build version.** `app/core/secure_http.py` hardcoded `"DupeZ/5.2.0"`. Same fix.

### Added
- **`app/__version__.py`** — Single source of truth for the runtime version string. All in-code references (dashboard title, update checker baseline, HTTP User-Agent, future telemetry) now import `__version__` from this module. Hardcoding version strings elsewhere in `app/` is now explicitly forbidden in the module docstring. `version_info.py`, `installer.iss`, `build.bat`, `README.md`, and `CHANGELOG.md` still carry their own copies (PyInstaller version resource, Inno Setup macro, build pipeline var, user-facing docs) and are kept in sync by convention per release.

### Notes
- No functional changes to network, map, voice, or firewall paths. Pure version-reporting fix.

---

## v5.2.2 — 2026-04-10 (Build Hardening: Torch/Whisper Isolation)

Patch release that stops PyInstaller's isolated analyzer child from crashing on `torch\lib\c10.dll` (WinError 1114 / access violation) during every build, and shrinks the portable exe by excluding the unused torch runtime.

### Fixed
- **PyInstaller builds no longer crash the isolated analyzer on whisper/torch.** Root cause: `voice_panel.py` and `clumsy_control.py` called `is_voice_available()` at module import time, which walked into `whisper → torch → _load_dll_libraries`, and a broken `c10.dll` raised an unrecoverable access violation (not a catchable Python `OSError`) inside PyInstaller's isolated child process. Both call sites are now deferred until view/panel instantiation and wrapped in a broad `except Exception` so even a C-level fault path degrades cleanly.
- **`dupez.spec`** — Added `whisper` and `openai-whisper` to `excludes` alongside the existing `torch`. Removed `whisper` from `hiddenimports`. Modulegraph now prunes the entire torch/whisper subtree during analysis.

### Changed
- **Portable `dupez.exe` is ~200 MB smaller** because torch and whisper are no longer dragged in through the voice-control import chain.

### Notes
- Voice control (`openai-whisper`) remains an optional runtime dependency. When installed alongside DupeZ, `voice_control.py` will still detect and enable it lazily on first panel instantiation. It is simply no longer bundled into the PyInstaller build or imported at module load time.

---

## v5.2.1 — 2026-04-10 (Map Fix + Resilient Optional Deps)

Patch release fixing the blank iZurvive map tab under DupeZ's elevated token and hardening optional-dependency import handling so broken installs (torch/whisper) can't crash startup.

### Fixed
- **iZurvive map now loads.** Root cause was Chromium's sandbox refusing to initialize under DupeZ's elevated (admin) token, killing the render process and producing a blank map tab. `dupez.py` now sets `QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --disable-gpu --disable-gpu-compositing` and `QT_OPENGL=software` at process entry before any PyQt6 import.
- **Broken optional dependencies no longer crash startup.** `app/ai/voice_control.py::_try_import` now catches `Exception` (not just `ImportError`) so a corrupted `torch` install (WinError 1114, DLL init failure) silently disables voice control instead of hard-crashing DupeZ.
- **QtWebEngine DLL load failures now surface.** `app/gui/dayz_map_gui_new.py` widened its exception handler around the QtWebEngine import from `ImportError` to `Exception` (Windows DLL failures raise `OSError`, not `ImportError`), and the placeholder widget now shows the real reason instead of a generic "not installed" message.

### Changed
- **`requirements.txt`** — `PyQt6-WebEngine` is now a declared dependency, pinned to match the `PyQt6` minor (`>=6.6.0,<6.12`). The two packages must resolve in a single pip pass or their Qt6 runtime wheels drift and `QtWebEngineCore.dll` fails to load.
- **`build.bat`** — Version is now defined once at the top via `DUPEZ_VERSION` / `DUPEZ_INSTALLER` variables instead of hardcoded in multiple places.

### Added — Dev Tools (`scripts/`)
- **`scripts/fix_webengine.bat`** — One-shot repair if PyQt6 / PyQt6-WebEngine wheels drift. Wipes every PyQt6/Qt6 wheel, clears the pip cache, reinstalls the package set in a single resolver pass, verifies `QWebEngineView` imports before exiting.
- **`scripts/diagnose_webengine.py`** — Minimal smoke test that bypasses DupeZ entirely and opens iZurvive in a bare `QWebEngineView`. Prints every load event, renderer-process crash, and JS console message. Use to isolate whether a map failure is in QtWebEngine itself or in DupeZ's wiring.
- **`scripts/README.md`** — Documents both tools.

### Housekeeping
- `.gitignore` — added `.pytest_cache/`.
- Moved `fix_webengine.bat` and `test_webengine.py` out of repo root into `scripts/`.

---

## v5.2.0 — 2026-04-09 (Indefinite God Mode + Dupe Engine + Hardening)

Breakthrough disruption release. Pulse-cycling god mode bypasses DayZ's connection quality monitor for indefinite red-chain. Dedicated dupe engine with precise timed disconnect-reconnect. Extended lag with connection preservation. Nation-state-grade security hardening across the entire codebase. Windows installer with Add/Remove Programs registration, auto-update from within the app, Getting Started guide, collapsible/reorderable UI sections, and splash screen overhaul.

### Added — Windows Installer & Distribution
- **`installer.iss`** — Inno Setup installer script. Installs to Program Files, registers in Add/Remove Programs (DisplayIcon, URLInfoAbout, URLUpdateInfo, HelpLink, EstimatedSize). App Paths registration so Windows finds `dupez.exe` by name. Desktop + Start Menu shortcuts. MOTW stripping via `RemoveMOTW()` Pascal procedure. `UsePreviousAppDir=yes` for upgrade-in-place. `CloseApplications=yes` to close running instances before upgrading. MinVersion=10.0.
- **`dupez.manifest`** — Windows application manifest declaring `requireAdministrator` execution level, OS compatibility for Windows 7–11, Per-Monitor DPI v2 awareness. Prevents Windows from applying compatibility shims.
- **`version_info.py`** — PyInstaller `VS_VERSION_INFO` resource embedding version 5.2.0.0, CompanyName, FileDescription, Copyright into the exe. Windows uses this for Properties dialog and SmartScreen trust scoring.
- **`build.bat`** — Rewritten as 4-stage pipeline: (1) PyInstaller build, (2) optional code signing via `DUPEZ_SIGN_CERT`/`DUPEZ_SIGN_PASS` env vars, (3) Inno Setup installer compilation, (4) PowerShell MOTW strip from `dist/`.

### Added — Auto-Update (Download & Install)
- **`app/core/updater.py`** — Upgraded from browser-open to direct download + silent install. `download_and_install()` downloads installer to temp dir with progress callback (64KB chunks), strips MOTW, launches with `/SILENT /CLOSEAPPLICATIONS`. `_get_install_dir()` reads InstallPath from `HKLM\SOFTWARE\DupeZ\DupeZ` registry. Prefers `*Setup*.exe` assets from GitHub Releases.
- **`app/gui/dashboard.py`** — Update dialog upgraded to 3-button: "Download & Install" (direct update), "Open in Browser" (manual), Cancel. Progress feedback via `_do_auto_update()` with auto-close after download.

### Added — Getting Started Guide
- **`app/gui/panels/help_panel.py`** — New sidebar view (🚀 icon, pinned to bottom). 10+ collapsible sections: Welcome (open by default), Getting Started, Clumsy Control, iZurvive Map, Account Tracker, Network Tools, Settings & Themes, Voice Control, GPC/Cronus, Troubleshooting, Keyboard Shortcuts. Dark glassmorphism styling matching `dark.qss`.

### Added — Collapsible & Reorderable Sections
- **`app/gui/clumsy_control.py`** — New `CollapsibleCard` widget with clickable ▶/▼ header toggle, ▲/▼ reorder buttons, `_swap_with()` layout manipulation. 9 sections wrapped: Preset, Auto-Tune/Smart Mode, Platform, Direction, Modules, Scheduler/Macros, Live Stats, Voice Control, GPC/Cronus Zen. Preset and Modules expanded by default, others collapsed.

### Changed — Splash Screen
- **`app/gui/splash.py`** — Window enlarged from 620×400 to 680×440. Explicit pixel anchors for title/version/tagline to prevent overlap. Pipeline slowed: 12 micro-steps at 45ms (was 6 at 40ms), 250ms holds (was 120ms), 2s final hold (was 1.2s). Glow and scan animations slowed for cinematic feel.

### Changed — Build Spec
- **`dupez.spec`** — Added `version=` and `manifest=` parameters. Excluded tkinter/tcl/_tcl_data to eliminate timezone data bloat. Expanded `upx_exclude` to prevent UPX corruption of large DLLs: Qt6Core, Qt6Gui, Qt6Widgets, Qt6Network, Qt6WebEngineCore (~200MB), Qt6WebEngineWidgets, QtWebEngineProcess.exe, python3*.dll, vcruntime*.dll, WinDivert.dll, WinDivert64.sys, and more.

### Fixed — Extraction Failures on Low-Spec Machines
- UPX compression of Qt6WebEngineCore.dll (~200MB) caused decompression failures on low-RAM Windows 10 machines. Fixed by adding all large DLLs to `upx_exclude`.
- Unnecessary `_tcl_data/tzdata` bundle (~7MB compressed) caused "Failed to extract" errors. Fixed by excluding tkinter/tcl from Analysis and filtering `_tcl_data` from datas.

### Removed
- `AUDIT_PASS_1.md`, `AUDIT_REPORT_TRIPLE_CHECK.md`, `FATAL_CRASH.txt` — Stale root-level debug artifacts.

### Added — God Mode v5.2 (Pulse Cycling)
- **Three operating modes:** Classic (original behavior), Pulse (default — block/flush cycling), Infinite (aggressive preset).
- **Pulse cycling:** Configurable block phase (default 3000ms) followed by flush phase (default 400ms). During BLOCK, all inbound queued — target sees red chain. During FLUSH, queued packets burst-release — quality monitor resets, sliding-window average stays below kick threshold indefinitely.
- **Infinite mode preset:** `godmode_infinite=True` → 5s block, 300ms flush, 2s keepalive, 200-packet flush cap. Maximum disruption while staying alive.
- **Packet classification:** Small inbound packets (<100 bytes) identified as server keepalive probes, preferentially passed during NAT keepalive windows. Maximum connection health signal with minimum game state leakage.
- **Teleportation effect:** During extended block phases, outbound movement reaches server continuously. Flush phase forces target's client to reconcile entire position delta at once — visual teleport.
- **Queue expanded:** 10K → 50K packets. Lag cap raised from 30s → 120s.

### Added — Dupe Engine
- **`app/firewall/modules/dupe_engine.py`** — New `DupeEngineModule` with three-phase state machine: IDLE → PREP → CUT → RESTORE → IDLE.
- **CUT phase:** Hard network cut — ALL traffic BOTH directions silently dropped. Configurable duration (1-25s, default 5s, safety clamped).
- **Trigger methods:** Timer-based (auto-transition after prep delay) or manual (`trigger_cut()` from UI/voice). Auto-restore or manual restore.
- **Multi-cycle support:** `dupe_cycle_count` for automated retry with configurable inter-cycle delay.
- **Action delay:** `dupe_action_delay_ms` parameter lets the inventory RPC reach the server before cutting.
- **Registered as `"dupe"` method** in CORE_MODULE_MAP with highest priority in module chain.

### Added — Extended Lag with Connection Preservation
- **`lag_preserve_connection`** — Auto-activates when `lag_delay` ≥ 5000ms. Periodically passes small keepalive-sized packets (<100 bytes) while holding large game state packets in the delay queue.
- **`lag_keepalive_interval_ms`** — Configurable keepalive pass-through interval (default 1500ms).
- **Enables 30s+ lag** without server timeout or NAT table expiry.

### Changed — Security Hardening (Nation-State Grade)
- **`app/core/crypto.py`** — CNSA 2.0 compliant cryptographic inventory. AES-256-GCM envelope encryption, HMAC-SHA384 integrity, SHA-384/512 hashing, PBKDF2-SHA-512 (600K iterations). Banned primitives enforced (no MD5, SHA-1, RC4).
- **`app/core/secrets_manager.py`** — Machine-bound KEK with encrypted at-rest storage for all secrets.
- **`app/core/secure_http.py`** — TLS 1.3 minimum for all outbound HTTP. Certificate verification always on. URL validation.
- **`app/core/validation.py`** — Strict allowlist input validation at every trust boundary. WinDivert filter tokenization. Updated with `dupe`, `pulse` methods and all v5.2 parameter ranges.
- **`app/core/patch_monitor.py`** — Full rewrite. Raw `urllib.request.urlopen` → `secure_get_json`. Atomic state persistence with HMAC-SHA384 companion files.
- **`app/ai/session_tracker.py`** — HMAC-SHA384 integrity verification on history file load/save.
- **`app/ai/smart_engine.py`** — HMAC-verified history loading.
- **`app/logs/audit.py`** — Hash-chained JSONL audit logging (tamper-evident).

### Changed — Architecture
- **`from __future__ import annotations`** added to all 36 non-`__init__` Python files for forward-compatible type hints.
- **Lazy singletons:** `theme_manager` → `get_theme_manager()`, `IS_ADMIN` → `_get_is_admin()`.
- **Lazy dependency resolution:** `voice_control.py` dependencies resolved on first use, not import time.
- **Lazy defaults:** `packet_classifier.py` defaults loaded lazily to break circular imports.
- **Public properties:** `tick_sync.py` TickEstimator `last_arrival` exposed via `@property`.

### Changed — Validation
- **`VALID_DISRUPTION_METHODS`** — Added `dupe` and `pulse`.
- **`VALID_PARAM_RANGES`** — Added: `godmode_pulse_block_ms` (500-30000), `godmode_pulse_flush_ms` (100-5000), `godmode_pulse_flush_max` (10-5000), `lag_keepalive_interval_ms` (0-10000), `dupe_prep_duration_ms` (0-30000), `dupe_cut_duration_ms` (1000-25000), `dupe_cycle_count` (1-10), `dupe_cycle_delay_ms` (0-30000), `dupe_action_delay_ms` (0-5000).
- **`lag_delay` cap** raised from 30000 → 120000ms. `godmode_lag_ms` cap raised from 30000 → 120000ms.

### Fixed
- **`app/core/updater.py`** — Removed dead import (`from urllib.request import Request, urlopen`) that was stale since migration to `secure_get_json`.
- **`app/gui/settings_dialog.py`** — Fixed theme manager backward compat break from lazy singleton refactor.
- **`app/gui/dashboard.py`** — Fixed `IS_ADMIN` and theme_manager imports for lazy singleton pattern.
- **`app/ai/voice_control.py`** — Fixed `_DEPS` NameError in `get_missing_packages()` after lazy refactor. Fixed incomplete lazy wiring in `list_input_devices()`, `set_input_device()`, `VoiceController.initialize()`.

### Stats
- **49/49 non-GUI modules** compile cleanly on import verification.
- **12 disruption modules** in CORE_MODULE_MAP + 2 tick-sync modules.
- **All unit tests pass** for god mode pulse cycling, dupe engine state machine, and lag connection preservation.

---

## v5.0.0 — 2026-04-09 (God Mode Engineering)

The deep-research release. Every phase from the DupeZ Deep Research & Next-Gen Roadmap implemented: statistical disruption models, packet classification, tick-synchronized bursts, asymmetric direction presets, native WinDivert batch API, ML-enhanced traffic analysis, and stealth/detection avoidance. Full codebase audit with zero rewrites on final pass. Architecture debt resolved — engine ABC, modules extracted.

### Added
- **Phase 1: Statistical Disruption Models** — Gilbert-Elliott two-state Markov chain, Pareto heavy-tail jitter, Token Bucket rate limiter, Correlated drop with temporal autocorrelation.
- **Phase 2: Packet Classification Engine** — UDP size/port heuristics, TCP flag analysis, per-flow frequency tracking. PacketCategory enum with SelectiveDisruptionFilter.
- **Phase 3: Tick-Synchronized Disruption** — TickEstimator, TickSyncDropModule, PulseDisruptionModule.
- **Phase 4: Asymmetric Direction Engine** — 14 named presets across 5 families. AsymmetricConfigBuilder fluent API.
- **Phase 5: Native WinDivert Batch API** — RecvEx/SendEx for up to 255 packets per syscall.
- **Phase 6: ML Network Profiler** — TrafficPatternAnalyzer, GameStateDetector (6 game states), AdaptiveTuner, SessionLearner.
- **Phase 7: Stealth & Detection Avoidance** — TimingRandomizer, NaturalPatternGenerator (4 patterns), StealthDrop/StealthLag, SessionFingerprintRotator.
- **Architecture: DisruptionManagerBase ABC** — Clean interface contract. Legacy aliases preserved.
- **Architecture: Module Extraction** — 10 core modules extracted from native_divert_engine.py into app/firewall/modules/ package.
- **Test Suite** — 216 tests across 6 test files, all passing.

---

## v4.0.0 — 2026-04-06 (Platform & Extensibility)

Major platform release. Plugin API, CLI mode, auto-updater, desync engine rewrite, God Mode overhaul with NAT keepalive, full opsec audit, and thread safety pass across the entire codebase.

### Added — Plugin API
- **`app/plugins/base.py`** — Base classes for all plugin types: `DisruptionPlugin`, `ScannerPlugin`, `UIPanelPlugin`, `GenericPlugin`. Each receives a reference to `AppController` on activation.
- **`app/plugins/loader.py`** — `PluginLoader` with full lifecycle: discovery, manifest validation, dynamic import, activation, deactivation, and hot-reload. Plugins live in `plugins/` with a `manifest.json` + Python entry point. Leak-safe loading cleans `sys.path` and `sys.modules` on unload.
- **`manifest.json` schema** — Declares name, version, description, type, entry_point, author, dependencies, and min DupeZ version. Validated on discovery.
- **Dashboard integration** — UI panel plugins automatically get a sidebar nav button and view stack entry. Loaded after core views during `setup_ui()`.
- **Controller integration** — `AppController._init_plugins()`, `get_plugin_info()`, `reload_plugins()`. Plugins unloaded cleanly on shutdown.
- **Example plugin: Ping Monitor** — Live latency panel showing real-time ping to all discovered devices. Demonstrates the full `UIPanelPlugin` lifecycle with thread-safe Qt signals.

### Added — CLI Mode
- **`app/cli.py`** — Full headless terminal interface. Subcommands: `scan`, `disrupt`, `stop`, `status`, `devices`, `plugins`. Interactive REPL mode with `dupez-cli interactive`.
- **Scriptable disruptions** — `dupez-cli disrupt <ip> --methods drop,lag --params '{"drop_chance":50}'`. Pipe-friendly output for automation.

### Added — Auto-Updater
- **`app/core/updater.py`** — `UpdateChecker` queries GitHub Releases API for latest version. Compares semver, offers one-click download via browser. Sync and async check modes.
- **Dashboard menu** — Help > Check for Updates triggers update check with dialog.

### Added — iZurvive Ad Blocker v2
- **Two-layer blocking** — Network-level `QWebEngineUrlRequestInterceptor` blocks ~28 known ad domains before requests leave the browser. DOM-level CSS/JS cleanup removes residual ad containers and iframes after page load.
- **OAuth login preserved** — Google/Steam login domains whitelisted so authentication flows are unaffected by ad blocking.

### Changed — Desync Engine Rewrite
- **Lag passthrough mode** — `LagModule` auto-enables passthrough when stacked with duplicate or out-of-order modules. In passthrough mode, lag queues a delayed *copy* of each packet but returns `False`, allowing the original to continue to downstream modules. This enables true lag+dupe+ood stacking for maximum desync. Previously lag consumed all packets (`return True`), silently preventing dupe/ood from ever firing.
- **`_init_modules()` auto-detection** — Engine inspects active method set on startup; if `{"duplicate", "ood"}` intersects active methods, `lag_passthrough` is enabled automatically with a log message.

### Changed — God Mode Overhaul
- **NAT keepalive system** — Periodically lets 1 inbound packet through unlagged (default every 800ms) to refresh Windows ICS NAT table mappings. Prevents silent packet drops during long freeze cycles caused by stale NAT entries. Configurable via `godmode_keepalive_interval_ms` (0 = disabled, used at intensity ≥ 0.95).
- **Burst-controlled flush on deactivation** — Queued inbound packets released in bursts of 50 with 5ms pauses between bursts to prevent packet storms that crash the target's network stack.
- **Full WinDivert NETWORK_FORWARD documentation** — `Outbound=True` means leaving gateway toward internet, `Outbound=False` means arriving from internet to be forwarded to target.
- **God Mode stats** — `stop()` logs inbound lagged/dropped/keepalive and outbound passed counters.

### Fixed — Duplicate Count
- **`DuplicateModule.process()`** — Now sends 1 original + N copies = N+1 total deliveries. Previously sent only N copies and consumed the original, so the target received N instead of N+1.

### Fixed — Thread Safety Pass
- **`data_persistence.py`** — All persistence operations protected by lock. Corrupt file recovery with atomic tmp → fsync → replace pattern.
- **`network_scanner.py`** — Executor access guarded by lock. Cache race condition resolved.
- **`state.py`** — Observer notifications marshalled to Qt thread. IP leak in `toggle_device_blocking()` fixed (2 call sites wrapped in `mask_ip()`).
- **`llm_advisor.py`** — `_conversation_history` reads/writes protected by `_history_lock`. `get_explanation()` wrapped in try/except with `_fallback_explanation` recovery. IP leak on line 156 fixed (`mask_ip()` applied before sending target IP to remote LLM API).
- **`gpc/device_bridge.py`** — Callback-outside-lock pattern prevents deadlock in device monitor.
- **`network_scanner.py`** — Enhanced `threading.Event` for lock-free thread-safe scan cancellation.

### Fixed — Scheduler / Macro
- **Repeat-only rule first-fire bug** — Rules with only a repeat interval now fire immediately on first tick instead of waiting one full interval.
- **Epoch-based delayed start** — Scheduled rules use epoch timestamps for delay calculation, eliminating clock drift on long-running sessions.
- **`QTimer.singleShot` for auto-stop** — Replaced `threading.Thread` sleep-then-stop pattern with Qt timer, eliminating race conditions between background thread and GUI thread.
- **Macro step callback** — `MacroStep` emits callback on completion for GUI timer synchronization.

### Security — Full Opsec Audit
- **`mask_ip()` everywhere** — All target IPs masked via `mask_ip()` in every log statement across the codebase (7 files, 12 call sites). Zero raw IPs in any log output.
- **LLM advisor IP leak closed** — Target IP was sent unmasked to remote LLM API in profile context. Now masked before transmission.
- **State.py IP leaks closed** — 2 log statements in `toggle_device_blocking()` logged raw target IP. Now masked.
- **No personal data in tracked files** — `dist/`, build artifacts, and user data files excluded via `.gitignore`.

### Changed — LLM Advisor
- **Complete system prompt rewrite** — Documents module chain order, passthrough mode, NAT keepalive mechanics, and 6 proven DayZ disruption scenarios with exact parameter values.
- **`godmode_keepalive_interval_ms`** added to `_PARAM_RANGES` (0–5000).
- **`_fallback_godmode` updated** — Includes keepalive interval scaled by intensity. Disabled (0ms) at intensity ≥ 0.95 for maximum freeze.
- **`_fallback_explanation` updated** — God Mode explanation includes NAT keepalive and burst flush details.

### Changed — Smart Engine
- **`_strategy_godmode` updated** — Generates `godmode_keepalive_interval_ms` scaled from 800ms (low intensity) to 0ms (max intensity). Hotspot connection type reduces lag by 20%.

### Changed — UI
- **Custom menu bar** — Embedded `QMenuBar` below frameless title bar with dark theme styling. ADMIN badge repositioned before version string.

### Changed
- **Version bump** — 3.5.0 → 4.0.0 across all modules, title bar, about dialog, AppUserModelID, and PyInstaller spec.
- **`dupez.spec`** — Plugin loader hidden imports added. `sys.path` cleanup modules included.
- **`clumsy_network_disruptor.py`** — Default params include `godmode_keepalive_interval_ms: 800`.

---

## v3.5.0 — 2026-04-03 (Live Stats + Distribution Polish)

Quality-of-life release: real-time packet stats dashboard, PyInstaller packaging improvements, and version bump.

### Added
- **Live Stats Dashboard** in Clumsy Control view — real-time packet counters (processed, dropped, passed, inbound, outbound) with auto-refresh every 1.5s. Includes drop rate progress bar, active engine count, and per-device breakdown table with method labels.
- **`NativeDisruptEngine.get_stats()`** — returns live packet counters dict from each engine instance.
- **`ClumsyNetworkDisruptor.get_all_engine_stats()`** — aggregates stats across all active disruption engines with per-device breakdown.
- **`AppController.get_engine_stats()`** — exposes aggregated engine stats to the GUI layer.
- **`_format_count()` helper** — human-readable packet counts (1.2K, 3.4M).

### Changed
- **`dupez.spec`** — Added hidden imports for voice (`sounddevice`, `whisper`) and GPC (`serial`, `serial.tools`, `serial.tools.list_ports`) so PyInstaller bundles optional dependencies correctly.
- **Version bump** — 3.3.0 → 3.5.0 across `main.py`, `dashboard.py`, `network_tools.py`, AppUserModelID.

---

## v3.4.0 — 2026-04-02 (God Mode + Voice + GPC)

Major feature release. Directional lag engine (God Mode), push-to-talk voice control via Whisper, and native CronusZEN/MAX GPC script integration.

### Added — God Mode
- **`native_divert_engine.py` → `GodModeModule`** — Directional lag engine using WinDivert packet direction detection. Delays inbound packets (server → target) while passing outbound untouched. Target freezes on other players' screens while your actions register in real time. Configurable inbound lag (0–5000ms) and optional inbound packet drop percentage.
- **Direction-aware filtering** — All disruption modules now implement `matches_direction()`. WinDivert `Outbound` bit (position 17 in addr bitfield) used for per-packet direction classification.
- **`NETWORK_FORWARD` layer support** — Enables God Mode on ICS/hotspot setups where the machine is the gateway.
- **God Mode preset** — 2000ms inbound lag, outbound untouched. One-click activation.
- **God Mode Aggressive preset** — God Mode + 30% inbound drop for harder freeze effect.
- **Smart Engine godmode strategy** — 6th goal strategy in AI auto-tune. Connection-type adjustments (hotspot reduces lag by 20%).
- **LLM Advisor godmode fallback** — Keyword-based God Mode interpretation with intensity scaling and hotspot detection when no LLM is available.

### Added — Voice Control
- **`app/ai/voice_control.py`** — Complete push-to-talk voice command module (~480 lines):
  - `VoiceEngine` — Audio capture via `sounddevice` InputStream callback (16kHz, mono, float32). Silence detection (RMS threshold), minimum length validation, max duration cap.
  - `VoiceController` — Wires VoiceEngine → OpenAI Whisper STT → LLMAdvisor → disruption config. Thread-safe callback marshaling to Qt main thread.
  - `VoiceConfig` dataclass — sample rate, channels, dtype, model name (tiny/base/small), language, silence threshold, min/max duration.
  - Lazy dependency checks — DupeZ runs without `sounddevice` or `openai-whisper` installed.
  - Simple voice commands: "stop"/"off" → stop disruption, "start"/"on" → start.
  - Input device listing and selection.
- **Voice Control UI panel** in Clumsy Control — INIT button, PUSH TO TALK button, model selector (tiny/base/small), mic selector, status label.

### Added — GPC / CronusZEN Support
- **`app/gpc/gpc_parser.py`** — GPC script tokenizer + recursive descent parser (~350 lines). Parses preprocessor directives, variables, main blocks, combo blocks, and functions into structured `GPCScript` objects.
- **`app/gpc/gpc_generator.py`** — GPC script generator (~350 lines). 4 built-in templates: DayZ Auto Dupe, Rapid Fire, God Mode Actions, Anti Recoil. Generates complete .gpc source synced with DupeZ disruption timing. Atomic file export.
- **`app/gpc/device_bridge.py`** — Cronus USB device detection + Zen Studio integration (~250 lines). Scans for VID 0x2508 via pyserial (WMI fallback on Windows). Background `DeviceMonitor` thread for connect/disconnect events. Auto-discovers Zen Studio library folder for direct .gpc export.
- **`app/gpc/__init__.py`** — Package init with full public API exports.
- **GPC UI panel** in Clumsy Control — Device status, template selector, description label, GENERATE/EXPORT/SYNC TIMING buttons, script preview.

### Fixed
- **100% drop fidelity** — Drop module now uses `continue` (discard packet) instead of re-injecting, guaranteeing true 100% drop when configured.
- **`llm_advisor.py`** — Missing `_fallback_godmode()` method caused `AttributeError` when godmode keywords matched without LLM. Added complete implementation with intensity scaling and hotspot detection.
- **`llm_advisor.py`** — False positive on bare "god" keyword (matched "good"). Removed; kept specific patterns ("god mode", "godmode", "freeze them", etc.).
- **`smart_engine.py`** — Goal key mismatch: GUI sent "god mode" (with space) but strategy map keyed on "godmode". Added `goal.replace(" ", "")` normalization.
- **`smart_engine.py`** — Hotspot adjustment never touched `godmode_lag_ms`. Added `*= 0.8` reduction in hotspot branch.
- **`clumsy_control.py`** — Voice command callback ran on background thread, modifying Qt widgets unsafely. Split into thread-safe marshal (`QMetaObject.invokeMethod`) + main-thread `@pyqtSlot` handler.
- **`clumsy_control.py`** — `_voice_controller` AttributeError when voice dependencies unavailable. Added `None` initialization in `__init__`.
- **`voice_control.py`** — Audio buffer appended from sounddevice callback thread without lock. Added `with self._lock:` guard on both append and read paths.
- **`llm_advisor.py`** — Removed unused `import os`.
- **`app/ai/__init__.py`** — Added voice control exports with `ImportError` fallback.

### Changed
- `smart_engine.py` — Goal strategies expanded from 5 to 6 (added godmode).
- `clumsy_control.py` — Smart Mode goal selector includes "God Mode". Voice and GPC panels added to control layout.
- `requirements.txt` — Added optional dependencies: `sounddevice>=0.4.6`, `openai-whisper>=20231117`, `pyserial>=3.5`.

---

## v3.3.1 — 2026-04-02 (Hardening Pass)

Full codebase audit — 11 fixes across 11 files targeting thread safety, crash resilience, frozen-exe compatibility, and correctness.

### Fixed — Critical
- **`blocker.py`** — Missing `log_warning` import crashed `clear_all_dupez_blocks()` at runtime.
- **`blocker.py`** — `is_active()` method shadowed `self.is_active` bool attribute; renamed to `get_active()`.

### Fixed — High
- **`data_persistence.py`** — `save_data()` used bare `json.dump`; crash mid-write corrupted file. Now uses atomic tmp → fsync → replace pattern.
- **`smart_engine.py`** — Hardcoded `"app/data/session_history.json"` broke in PyInstaller builds. Now uses `_resolve_data_directory()`.
- **`logger.py`** — Relative `"logs"` directory resolved to `System32\logs` in frozen exe. Added `_resolve_log_directory()` with `sys.frozen` detection.

### Fixed — Medium
- **`state.py`** — `_observers` list had no thread protection. Added `threading.Lock` to `add_observer()` and `notify_observers()`.
- **`controller.py`** — `start_auto_scan()` never reset `stop_scanning` flag, preventing auto-scan restart after manual stop.
- **`network_profiler.py`** — `ip.startswith("172.2")` incorrectly matched public IPs 172.200-255.x.x. Added proper RFC1918 172.16.0.0/12 range check.
- **`session_tracker.py`** — `_active_sessions` dict mutations in `start_session()`/`end_session()` were unprotected. Now guarded by `self._lock`.

### Fixed — Low
- **`native_divert_engine.py`** — Out-of-Order module had unbounded packet buffer. Added `MAX_BUFFER=64` safety valve.
- **`helpers.py`** — 350-entry duplicate emoji replacement dict replaced with single `encode('ascii', errors='replace')` call.

### Changed
- **`main.py`** — Version log updated to 3.3.0. AppUserModelID updated to `com.dupez.app.3.3`.
- **`dashboard.py`** — Window title updated to "DupeZ v3.3.0".

---

## v3.3.0 — 2026-04-02 (Network Intelligence)

Network intelligence toolkit. Live traffic monitoring, latency overlay for gameplay, and standalone port scanner.

### Added
- **`app/gui/network_tools.py`** — New Network Tools module with 4 tab views:
  - `TrafficMonitorWidget` — Real-time per-interface bandwidth table. Shows bytes sent/recv, rate in KB/s with color-coded thresholds, total throughput bar.
  - `LatencyOverlayWidget` — Continuous ping monitor with sparkline graph. Floating always-on-top transparent overlay mode for gameplay (draggable, right-click to close).
  - `PortScannerWidget` — TCP port scanner with preset port sets (Common 100, Gaming, Web, All 1-1024, Full 1-65535). Threaded scanning with progress bar, service identification for 25+ known ports.
- **Network Tools view** — 4th sidebar nav button (📡) in dashboard. Accessible via Ctrl+4.

### Changed
- `dashboard.py` — Expanded from 3-view to 4-view architecture (Clumsy | Map | Accounts | Network Tools).

---

## v3.2.0 — 2026-04-02 (Multi-Target & Scheduling)

Multi-device disruption, timed disruptions, macro chains, and profile sharing.

### Added
- **Multi-Device Disruption** — MULTI toggle in device list enables selecting multiple targets. DISRUPT/STOP buttons operate on all selected devices simultaneously.
- **`app/core/scheduler.py`** — Disruption scheduler + macro engine (~280 lines):
  - `ScheduledRule` — Timer-based disruption rules with HH:MM triggers, duration, and repeat intervals.
  - `DisruptionMacro` / `MacroStep` — Named sequences of disruption steps with per-step timing and repeat control.
  - `DisruptionScheduler` — Background thread scheduler with atomic JSON persistence.
- **Scheduler UI** in Clumsy Control view:
  - Duration/Delay spinboxes for timed disruptions
  - TIMED DISRUPT button — disrupt for N seconds, then auto-stop
  - RUN MACRO — execute saved macros or generate Quick Macros (3-step: light → current → heavy)
  - STOP MACRO — halt active macro execution
- **Import/Export Profiles** — IMPORT and EXPORT buttons in profile panel. Export profiles as standalone JSON, import from file.

### Changed
- `clumsy_control.py` — Device checkboxes now support multi-select mode. Target label shows count when multiple selected. DISRUPT iterates all targets.
- `controller.py` — Scheduler integrated into controller lifecycle (start on init, stop on shutdown).

---

## v3.1.0 — 2026-04-02 (Smart Mode + QoL)

AI-powered auto-tuning, system tray mode, device nicknames, and scan caching.

### Added
- **`app/ai/` module** — Complete AI auto-tune subsystem (4 new files, ~1,500 lines):
  - `network_profiler.py` — Probes target IP in real-time: RTT, jitter, packet loss, bandwidth estimation, hop count, port fingerprinting, device type inference, connection quality scoring (0-100).
  - `smart_engine.py` — Maps network profiles to optimal disruption parameters. 5 goal strategies (disconnect, lag, desync, throttle, chaos) with connection-type adjustments (hotspot/LAN/WAN) and device-type tuning (console/PC/mobile). Intensity slider (0-100%) scales all parameters.
  - `llm_advisor.py` — Natural-language disruption tuning via Ollama (local Mistral 7B) or any OpenAI-compatible API. Describe what you want in plain English → get a tuned preset. Falls back to keyword-based interpretation when no LLM is available.
  - `session_tracker.py` — Logs every disruption session (profile snapshot, config used, duration, user rating). Feeds back into the engine to improve future recommendations. Atomic JSON persistence.
- **AI Auto-Tune UI panel** in Clumsy Control view:
  - Goal selector (Auto, Disconnect, Lag, Desync, Throttle, Chaos)
  - Intensity slider with purple accent theme
  - "ASK AI" text input for natural language requests
  - PROFILE button (analyze target without disrupting)
  - SMART DISRUPT button (profile + auto-tune + disrupt in one click)
  - Live recommendation display with reasoning, confidence bar, and estimated effectiveness
- **`app/core/profiles.py`** — Profile system for saving/loading/sharing named disruption configs. JSON-based, supports import/export, tracks usage count and timestamps.
- **Session history** — Persistent log of past disruptions with target profiles, configs used, and effectiveness ratings. Enables the engine to learn from past sessions.
- **Tray Mode** — System tray icon with context menu (Show/Hide, disruption status, Stop All, Quit). Minimize-to-tray on window close. Ctrl+Shift+D global hotkey to toggle visibility.
- **Device Nicknames** — Right-click any device in the table to set/rename/clear a friendly nickname. Nicknames persist across sessions (stored in `device_nicknames.json`). Shown in gold (#fbbf24) in the Nickname column.
- **Scan Result Caching** — `DeviceCacheManager` persists last scan results to `device_cache.json`. Device list pre-populated on launch from cache.

### Changed
- `dashboard.py` — Version bumped to 3.1.0. System tray icon with tooltip showing active disruption count. Hotkey manager integration. Close event minimizes to tray by default (Quit via tray menu or Ctrl+Q). Hotkeys help dialog updated.
- `clumsy_control.py` — Device table expanded to 7 columns (added Nickname). Integrated Smart Mode panel between Preset selector and Direction toggle. Session tracking wired to stop/stop-all buttons. Context menu for nickname management.
- `controller.py` — Device cache loaded on init, saved after each scan.
- `data_persistence.py` — Added `NicknameManager` and `DeviceCacheManager` with global instances.
- Smart Mode now defaults to AI-recommended settings when enabled, automatically populating all module checkboxes and sliders.

---

## v3.0.1 — 2026-04-01

Production hardening pass for public community release.

### Added
- `.gitattributes` — Cross-platform line ending normalization. Binary files (DLLs, .sys, .exe, .ico) marked binary to prevent git corruption.
- Atomic file writes for `settings.json` — writes to `.tmp`, fsyncs, then `os.replace()` to prevent mid-write corruption.
- Settings resilience — `load_settings()` auto-recovers to clean defaults on corrupt/partial JSON.
- Self-contained settings dialog stylesheet (`SETTINGS_STYLE`) — immune to app-level theme changes.
- Complete QSS coverage in `dark.qss` — QSlider, QTextEdit, QDialog, QMenuBar, QMenu, QSpinBox buttons, QComboBox dropdown.
- Missing QSS rules in `light.qss` — QSpinBox, QTextEdit, QDialog.
- Full settings documentation in README — all 5 tabs with every field, default, and range.

### Changed
- Settings dialog completely rewritten — 5-tab layout (General, Network, Smart Mode, Interface, Advanced), all 28 `AppSettings` fields wired end-to-end.
- Settings dialog styled to match cyber HUD theme — glassmorphism background, cyan accents, color-coded buttons.
- `state.py` — Hardened `load_settings()` filters unknown keys, catches `JSONDecodeError`/`TypeError`, auto-regenerates on corruption.
- `state.py` — `save_settings()` uses atomic write pattern (tmp + fsync + os.replace).
- `profiles.json` — Stripped PS5/XBOX device-specific profiles, replaced with generic defaults.
- `logger.py` — Renamed `ps5_detection()` → `device_detection()`, `log_ps5_detection()` → `log_device_detection()` (backward-compat aliases kept).
- All documentation IPs replaced with RFC 5737 addresses (198.51.100.x).

### Removed
- 14,800+ lines of dead code: `development/` test suites, PS5-specific scripts and GUI (`ps5_gui.py`), launcher batch files, maintenance scripts, `strip_dead_code.ps1`.
- Dead UI controls from settings: `log_to_file_checkbox`, `interface_combo`, `custom_network_edit`.
- Unused imports from settings dialog: `QLineEdit`, `QProgressBar`, `QFileDialog`, `QColorDialog`, `QFontDialog`, `QColor`, `Dict`, `Any`.

### Fixed
- Corrupted `settings.json` — was truncated mid-write (missing closing brace, partial field). Rebuilt with clean defaults.
- Settings dialog stylesheet overwritten by theme changes — now re-applies `SETTINGS_STYLE` in `apply_theme()`, `start_rainbow_mode()`, `stop_rainbow_mode()`.
- Qt combo box feedback loops — `blockSignals()` guards prevent recursive signal firing during programmatic updates.

### Security
- Zero personal IPs, emails, debug artifacts, or secrets in tracked code.
- All example IPs use RFC 5737 documentation ranges.

---

## v3.0.0 — 2026-03-30 (The Strip)

Complete architectural overhaul. Stripped 90+ dead files (~40,000 lines). Rebuilt from 5-view bloated dashboard to clean 3-view tool.

### Added
- `clumsy_control.py` — New main view. Device scanner + per-device disruption controls with sliders, presets, method checkboxes, session timers.
- Disruption presets: Light Lag, Heavy Lag, Full Disconnect, Desync, Bandwidth Cap, Custom.
- Per-method parameter sliders: Drop %, Lag ms, Throttle %, Duplicate %, Corrupt %, RST %.
- Map selector dropdown: 8 maps (Chernarus+ sat/topo, Livonia, Namalsk, Sakhal, Deer Isle, Esseker, Takistan).
- MutationObserver-based ad blocker for iZurvive (catches dynamically injected ads).
- Account tracker dark theme with status-colored statistics bar.

### Removed
- ML module (MoE engine, inference, embeddings, anomaly detection, threat classifier, report generator — 11 files, ~5,200 lines)
- Surveillance module (DPI, network intelligence, behavioral profiler — 3 files, ~1,600 lines)
- Counter-surveillance module (anomaly detector, deception engine, anti-MITM, TSCM — 4 files, ~1,600 lines)
- Security module (crypto engine, anti-forensics, integrity monitor, encrypted DB, auth, audit logger — 8 files, ~3,500 lines)
- Research module (OSINT engine, threat intel — 2 files, ~1,060 lines)
- Plugin system (advanced plugin system, plugin manager, secure executor, gaming control — 6 files, ~3,000 lines)
- Privacy module, health module, PS5 module
- Mesh networking (gossip protocol, node discovery, distributed tasks)
- 17 orphaned GUI files (old map, gaming dashboard, tips/tricks, topology views, duplicate device lists, etc.)
- 7 redundant firewall modules (enterprise disruptor, network disruptor, netcut, internet dropper, UDP interrupter, etc.)
- 8 redundant core modules (smart mode, stability optimizer, traffic analyzer, data pipeline, etc.)
- 9 redundant network modules (gaming optimizer, duping optimizer, server discovery, multi-protocol scanner, etc.)
- TipsTicker footer, stability optimizer integration, CPU monitoring timers, animation timers
- All root-level debug artifacts (crash logs, one-off scripts, enhancement blueprint)

### Changed
- `main.py` — Stripped to clean startup. Only clumsy disruptor in shutdown path. Version bumped to 3.0.0.
- `controller.py` — Gutted from 742 to 285 lines. Direct clumsy integration. Removed smart mode, plugin manager, traffic analyzer, enterprise disruptor.
- `dashboard.py` — Complete rewrite. 3-view sidebar rail (Clumsy | Map | Accounts). 1,732 → 348 lines.
- `dayz_map_gui_new.py` — Enhanced from 75 to 137 lines. Map selector + improved ad blocker.
- `dayz_account_tracker.py` — Injected cascading dark theme. Fixed 23 empty `setStyleSheet("")` calls. Status-colored statistics.

### Stats
- Before: 110+ files, ~60,800 lines
- After: 14 files, ~6,600 lines
- Reduction: 89%

---

## v2.0.0 — Previous (Legacy)

Major UI optimization. 5-view dashboard with sidebar rail. iZurvive map integration. Account tracker. Multiple network disruptors.

## v1.0.0 — Initial

Basic network scanner with device blocking.
