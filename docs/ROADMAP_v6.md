# DupeZ v6.x Feature Roadmap

> **Archived planning document.** Some proposals below predate the
> owned/authorized-lab product boundary adopted on June 25, 2026. They are not
> approved implementation work. The current roadmap and
> `docs/competitive_audit.md` supersede any server-integrity, bypass/evasion, or
> unauthorized public-server use proposals in this file.

Scoping doc for the six features Grihm selected from the v5.6.x deep-research pass. Each entry has: scope, architecture, effort estimate, dependencies, and a concrete next-action.

Ordering recommendation at the bottom.

---

## Feature 2 — Dupe-attempt log (PARTIAL in v5.6.8)

**Status:** backend reader landed in v5.6.8. UI panel deferred.

### What v5.6.8 ships
`LearningLoop.recent_episodes(limit, labeled_only)` and `LearningLoop.session_summary()` — read-only query API over the existing `app/data/episodes/episode_*.jsonl` store. Returns structured `EpisodeSummary` rows for the GUI to render.

### What v5.6.9 needs to add
A `DupeHistoryPanel` widget. Recommended layout:
- Header strip with `session_summary()` counts (total / labeled / success rate / severed-vs-never-cut breakdown).
- Filterable table: `start_ts | target_profile | preset | methods | duration_s | cut_state | outcome`.
- Right-click → "Re-run with same params" (calls `disrupt_device` with `params` from the row).
- Export to CSV (existing patterns from the tracker).

### Effort
3-4 hours. Most of the work is QTableView wiring + filter chips; the data layer is done.

### Open questions
- Where in the GUI? Could go as a new tab next to Account Tracker, or as a slide-out drawer from the main dashboard. Tab is simpler.
- How aggressive should the "re-run" affordance be? Could be a problem if it lets an operator stomp on an existing active disruption. Recommend: disabled when a disruption is already running on that target.

---

## Feature 4 — Hotkey macros (v5.6.9 candidate)

### Scope
Bind any preset to a global hotkey that fires while DupeZ is *not* the foreground window. Primary use case: trigger a cut while the operator is in DayZ at a keyboard or playing on console with the PC hotkey-bridging.

### Architecture
- **Registration:** Win32 `RegisterHotKey()` via ctypes. Avoids the `keyboard` PyPI library, which installs a system-wide low-level hook that some server-integrity heuristics flag.
- **Receiver thread:** dedicated worker thread that pumps Windows messages via `GetMessageW`. Emits a `pyqtSignal` on `WM_HOTKEY` (msg = 0x0312). Main thread translates the hotkey ID to a registered action and dispatches.
- **Storage:** `app/config/hotkeys.json`, structured as:
  ```json
  {
    "version": 1,
    "bindings": [
      {"id": 1, "mods": ["ctrl", "alt"], "key": "1", "action": "preset:Red Disconnect"},
      {"id": 2, "mods": ["ctrl", "alt"], "key": "2", "action": "preset:Lag"},
      {"id": 3, "mods": ["ctrl", "alt"], "key": "s", "action": "stop:selected"},
      {"id": 4, "mods": ["ctrl", "alt"], "key": "x", "action": "stop:all"}
    ]
  }
  ```
- **Actions:** strings parsed by an action-dispatch table. Start with:
  - `preset:<name>` — fire preset against the currently selected target(s) in the device table.
  - `stop:selected` — stop disruption on selected targets.
  - `stop:all` — stop everything.
  - `cycle:preset` — rotate through a configured preset list.
- **Settings UI:** new "Hotkeys" tab. QComboBox for modifier set + QLineEdit (single-char) for key + QComboBox for action. Bind button calls `RegisterHotKey()`; conflict (`ERROR_HOTKEY_ALREADY_REGISTERED`) shows a clear message naming the conflicting binding.

### Effort
1-1.5 days. Half the work is the Win32 plumbing (RegisterHotKey + message pump + Qt signal bridge), half is the settings UI + persistence.

### Dependencies
None new. ctypes + existing PyQt6.

### Risk
- **BattlEye flagging:** unclear. `RegisterHotKey()` is a documented OS API used by hundreds of legitimate apps (OBS, Steam, etc.); should be safe. The `keyboard` library would NOT be safe.
- **Fullscreen exclusive games:** Win32 hotkeys generally fire regardless of foreground app, but some fullscreen-exclusive games (especially older DX9 titles) capture all input. DayZ uses Vulkan/DX11 in borderless-windowed mode by default — hotkeys should fire normally.

### Open question
- Should we also support `pyqtSignal`-only hotkeys (Qt-window-focused)? Useful as a fallback for users on Linux/Mac builds, but DupeZ is Windows-only so probably skip.

---

## Feature 13 — Plugin marketplace (v5.7.x / v5.8.x)

### Scope
A signed-plugin distribution channel so the community can author and share presets, macros, dupe recipes, and possibly custom disruption modules — without each user having to manually verify trust.

### Existing foundation
- `app/plugins/` already has Ed25519 signature verification (the "H4 plugin Ed25519 signature + capability sandbox" task from the v5.5 hardening pass). Trust model is in place; what's missing is distribution.

### Architecture

**Backend (new):**
- A simple static site (S3 + CloudFront, or GitHub Pages) serving:
  - `marketplace/index.json` — list of plugins with metadata (name, author, version, description, capabilities, signature_url, plugin_url).
  - Per-plugin URLs for the signed bundle.
- Maintainer signs `index.json` with the same Ed25519 key as updates, so the marketplace itself can't be MITM'd. Plugins use the same signature envelope format as the auto-updater manifest (`update_verify.py` infrastructure is fully reusable).
- New trust tier: "Verified" plugins signed by the project key; "Community" plugins signed by author keys allow-listed at install time.

**Client (new modules):**
- `app/plugins/marketplace.py` — fetches index, verifies signature, exposes browse/install API.
- `app/gui/panels/marketplace_panel.py` — UI: search, filter by capability, install button, version-update notifier.

**Plugin format:**
- ZIP bundle: `plugin.toml` (manifest) + `signature.sig` + Python files. Existing `plugins/` loader already handles unzip + signature verify.

### Effort
1-2 weeks total.
- Backend infrastructure: 2-3 days (static site + sign-and-publish script for new plugins).
- Client browse/install flow: 3-4 days.
- UI panel: 2-3 days.
- First-batch curated plugins: 2-3 days (porting existing community presets / writing 2-3 reference recipes).

### Dependencies
- A web host. GitHub Pages + a `marketplace` repo is the cheapest path; CloudFront is the production-grade option if download volume grows.
- A sign-and-publish workflow for new plugins (similar to v5.6.6's release signing, with a separate marketplace key).

### Risks
- **Curation overhead.** Even verified plugins need review. Without staffing, the "Verified" tier stays small. "Community" tier could grow organically but trust falls on the user.
- **Malicious plugins.** Even signed plugins run with the host's privileges. The capability sandbox limits damage but isn't a full security boundary. Recommend: document the trust model prominently and surface a permissions dialog on first install of each new plugin.
- **Plugin API stability.** Once external plugins exist, the internal API becomes a contract. Plan for a versioned API: `app.plugins.api.v1`, etc.

### Open questions
- Curation policy: who decides what gets "Verified"?
- Hosting cost target: $0/month (GitHub Pages) or pay for CloudFront for faster CDN?
- Payment / paid plugins ever a path? Probably not.

---

## Feature 14 — Mobile companion (v5.8.x / v5.9.x)

### Scope
Trigger DupeZ cuts from a phone over LAN. Use case: operator is at the console, away from the PC, needs to fire a preset.

### Architecture

**PC side (DupeZ host):**
- New module `app/companion/server.py` — WebSocket server on `0.0.0.0:9876` (configurable).
- Pairing: QR code in the GUI containing `dupez://pair?token=<32-byte-hex>&port=9876&fingerprint=<sha256>`. User scans with phone app.
- Authentication: each command is HMAC-signed with the paired token. Replay protection via nonce + timestamp window.
- Capability surface (intentionally narrow):
  - `list_targets` → current device table snapshot.
  - `list_presets` → preset names.
  - `fire(target_id, preset, duration_s)` → start a disruption.
  - `stop(target_id)` / `stop_all`.
- No remote settings changes, no exec, no file access. Closed allowlist.

**Phone side (new mobile app):**
- Tauri or Flutter for cross-platform (iOS + Android). Flutter is faster to ship.
- Minimal UI: device list, preset buttons, stop button. Connection status indicator.
- Settings: re-pair (rescan QR), preferred server IP.

### Effort
1.5-2 weeks total.
- PC WebSocket server + pairing + HMAC layer: 3-4 days.
- Mobile app: 5-7 days for a clean MVP on both platforms.
- Testing across phone↔PC pairs, including reconnect behavior on network changes: 2-3 days.

### Dependencies
- A mobile build pipeline. App Store / Play Store sideloading is feasible for limited distribution, or use a TestFlight + Internal Track approach to avoid review friction.
- The HMAC pairing infrastructure is mostly already in `app/core/second_factor.py` — reusable.

### Risks
- **App Store approval.** Apple may reject an app that exists primarily to interact with a "game-network-disruption tool" depending on how it's described. Recommend framing as a generic LAN-trigger remote. Android sideloading has a different review path.
- **LAN-only constraint.** Mobile networks vary; some carriers NAT clients so the phone can't reach the PC. Document: "must be on same WiFi as DupeZ host." A future Tier 2 could add a Tailscale-style overlay but that's a separate project.

### Open questions
- iOS, Android, or both?
- Should the mobile app show the dupe history / cut verifier state, or stay minimal as a remote?

---

## Feature 15 — Baseline drift telemetry (v5.7.x)

### Scope
Passive monitor that watches DupeZ's own disruption patterns and warns the operator when the packet shape starts looking statistically unusual compared to a calibrated baseline. Goal: catch server-integrity heuristic drift before it becomes an operational risk.

### Architecture

**Calibration phase:**
- During normal gameplay (no disruption active), the engine records baseline windows of the operator's outbound packet stream: inter-arrival distribution, packet-size distribution, payload entropy, port distribution. Stored as `app/data/baseline/<game_profile>.json`.
- 30-60 minutes of clean play is enough to establish a stable baseline.

**Detection phase:**
- During each cut, the engine compares the live drop/lag pattern against the baseline using a few distance metrics:
  - **Inter-arrival KS test** — is the inter-packet gap distribution still close to baseline?
  - **Drop-rate Z-score** — is the loss rate within expected jitter for this network class?
  - **Payload-entropy delta** — are dropped/corrupted packets bunching in a way real loss never does?
- Threshold breach → log a `diagnostic_drift_high` event and surface a toast: "your current preset is drifting outside the baseline by N standard deviations; consider switching presets."

**Module location:**
- `app/security/detection_monitor.py` — calibration + live comparison logic.
- Hook into `native_divert_engine` at packet-drop and packet-lag sites (already have the packet-counter telemetry from v5.6.5).

### Effort
3-5 days.
- Baseline capture + storage: 1 day.
- Statistical comparison engine: 1-2 days (scipy + numpy already in deps).
- UI surfacing (toast + risk indicator on dashboard): 0.5 day.
- Per-game-profile thresholds + tuning: 1 day.

### Dependencies
- `scipy.stats` — already a transitive dependency.

### Risk
- **False positives.** A noisy network or a particularly aggressive preset will trip the detector even when nothing's actually wrong. The risk score needs to be *advisory*, not blocking. Threshold tuning will take real-world data.
- **Doesn't actually detect server policy.** It measures distance from the operator's own baseline, which is a proxy. If BattlEye's heuristics change in a way that catches patterns the operator never produced, this won't help. Frame it as "your packet shape is unusual," not "server policy may flag it" — those are different claims.

### Open questions
- Should the detector also auto-suggest a different preset when it trips? Tempting but adds complexity. Recommend: v1 is advisory-only.
- Per-server baselines vs per-game baselines? Per-game is simpler and probably enough.

---

## Feature 17 — Cross-game support (v5.8.x / v5.9.x)

### Scope
Extend DupeZ beyond DayZ to other survival/online games where network-shape disruption produces useful outcomes (Rust, ARK, Valheim, etc.).

### Existing foundation
- `app/config/game_profiles/dayz.json` is already structured. Other game profiles can be added as sibling files.
- `app/firewall/target_profile.py` does the auto-detection. Currently DayZ-specific but the layering check (hotspot vs WiFi vs local) is game-agnostic.

### Architecture

**Per-game profile schema:**
- Server port ranges (Rust uses 28015 UDP, ARK uses 7777, etc.).
- Game-specific characteristics: TCP-heavy vs UDP-heavy, average packet rate, A2S query support (most Source-engine games).
- Recommended presets per game (Rust dupes work differently than DayZ).
- Cut-verifier strategy per game (some games respond to A2S, some don't — Rust uses RCON, Valheim uses a custom query).

**Detection extensions:**
- Process detection: scan for active game processes (`Dayz.exe`, `RustClient.exe`, `ShooterGame.exe`, `valheim.exe`). Switch profile based on what's running.
- Per-process traffic filtering: WinDivert can scope filters to a specific PID, which lets the operator run two games and disrupt one without affecting the other.

**Module changes:**
- `app/core/game_profile_manager.py` (new) — loads and selects the active profile.
- `app/firewall/clumsy_network_disruptor.py` — accept `game_profile` as a parameter, defaults to "auto" (detect by running process) or "dayz" (current behavior).
- New profiles to ship:
  - `rust.json` — Rust (Facepunch).
  - `ark.json` — ARK: Survival Ascended.
  - `valheim.json` — Valheim.
  - `generic_udp.json` — fallback for any UDP-based online game.

### Effort
1-2 weeks total.
- Profile manager + detection: 2-3 days.
- Per-game profile authoring + testing: 3-5 days per game (Rust + ARK + Valheim covered).
- Cut-verifier protocol generalization (A2S, RCON, custom query): 2-3 days.
- UI: game-selector dropdown + auto-detect indicator: 1 day.

### Dependencies
- Real-world testing per game. The operator (Grihm) or a community tester needs to verify each profile actually produces the desired outcome in-game. This is the long-tail cost; per-game tuning probably takes a week of real play per title.

### Risks
- **Each game's server-integrity stack is different.** EAC (Rust), BattlEye (DayZ, ARK), proprietary (Valheim). What works on one may flag on another. Per-game baseline + detection monitor (Feature 15) helps here.
- **Game updates break profiles.** When Rust patches its netcode, the profile needs re-tuning. Maintenance burden grows linearly with supported games.
- **Scope creep.** "Add support for X" requests will be constant. Recommend: ship Rust + ARK first (largest survival audiences after DayZ), then evaluate community demand.

### Open questions
- Profile format versioning: when a game's netcode changes, how do we ship a profile update without a full client release? Probably needs Feature 13 (plugin marketplace) so profiles can be hot-shipped as community plugins.

---

## Recommended ordering

```
v5.6.8  ┃ Save-bug fix + recent_episodes() backend         ← SHIPPING NOW
v5.6.9  ┃ Dupe-history UI panel + hotkey macros            ← 2-3 day release
v5.7.0  ┃ Baseline drift telemetry                          ← 1 week release
v5.7.x  ┃ Cross-game profiles (Rust + ARK)                  ← 2 week release
v5.8.0  ┃ Plugin marketplace                                ← 2 week release
v5.9.0  ┃ Mobile companion                                  ← 2 week release
```

**Rationale:**
1. Hotkey macros and the dupe-history UI are low-risk, high-utility, and the user-facing complement to what v5.6.8 ships. Bundle them as v5.6.9.
2. Baseline drift telemetry feeds every other feature (cross-game tuning, mobile-triggered cuts, marketplace plugins all benefit from the risk signal). Build it before they need it.
3. Cross-game support multiplies the addressable surface area and pairs naturally with the plugin marketplace (community-authored game profiles).
4. Plugin marketplace is the platform play; once it's live, individual feature releases compound because contributors can extend without core changes.
5. Mobile companion is last because it's the most surface-area-heavy and the least technically reusable across the other features.

Alternative ordering if the priority is **community growth over technical capability**: ship the plugin marketplace earlier (v5.7.0), accept rougher edges, let the community fill in.
