# ADR-0001 QA Matrix — Split-Elevation Rollout

Hardware / OS matrix for validating the DUPEZ_ARCH=split rollout before
flipping the feature flag default from `inproc` to `split`.

The non-negotiable acceptance criterion across every cell: **zero
observable regression in duping behavior, lag features, or packet-path
latency histograms compared to the inproc baseline.** The map GUI
fluidity is the only thing that's allowed to differ — and only in the
positive direction.

## Test machines

| ID   | Role                     | CPU             | GPU                        | RAM   | OS                       |
|------|--------------------------|-----------------|----------------------------|-------|--------------------------|
| M1   | Modern reference         | Ryzen 7 7700X   | RTX 4070                   | 32 GB | Win 11 23H2              |
| M2   | Mid-tier integrated      | i5-1240P        | Intel Iris Xe (driver ≥30) | 16 GB | Win 11 22H2              |
| M3   | Old / blocklisted GPU    | i5-6500         | Intel HD 530 (blocklisted) |  8 GB | Win 10 22H2              |

M1 represents the upper tier (tier1_hw). M2 represents the typical
player (tier2_swiftshader or tier1_hw depending on driver date). M3 is
the no-GPU baseline (tier3_cpu) and MUST behave exactly like today's
shipping build.

## Feature flag matrix (per machine)

Each machine runs all six permutations:

| # | DUPEZ_ARCH | DUPEZ_ELEVATION | DUPEZ_MAP_RENDERER |
|---|------------|------------------|---------------------|
| 1 | inproc     | (n/a)            | (n/a — forced CPU)  |
| 2 | split      | runas            | auto                |
| 3 | split      | runas            | software            |
| 4 | split      | scheduled_task   | auto                |
| 5 | split      | runas            | gpu                 |
| 6 | split      | auto             | auto                |

Configuration 1 is the baseline. Configurations 2–6 are the new path.
Configuration 3 on every machine must be byte-for-byte identical to
config 1 on the map side (both are CPU raster).

## Duping / lag path — MUST match baseline

For each machine × config, run the scripted duping sequence:

1. Start DupeZ, confirm engine status shows `running`.
2. Add the PS5 console to the target list and trigger the standard
   duping profile (5-minute warm-up, then 10 runs).
3. Toggle hotkeys F5/F9/F10/F11/F12 during live play — verify every
   hotkey registers in the GodMode recorder.
4. Trigger `clear_all_dupez_blocks` via the GUI, confirm netsh rules
   are removed.
5. Stop the engine, verify no orphaned WinDivert handles, no orphaned
   netsh rules, no leaked helper processes.

Acceptance — for every step:
- Hotkey latency (user perception) identical to baseline.
- Duping success rate within noise of baseline (N=10, no statistically
  significant drop).
- No new crashes in `app/logs/dupez.log` or `firewall_helper.log`.
- Packet counters in `get_engine_stats()` show no drop rate regression.

## Map fluidity — MUST improve or match baseline

For each machine × config, load Chernarus+ (Satellite), pan and zoom
for 60 seconds, and record:

- Visual FPS (by eye — stutter, smooth, buttery).
- Leaflet marker-drag latency (drag a pin across the map, time-to-land).
- Any rendering artifacts (tiles dropping, white flashes, tearing).

Expected results:

| Machine | inproc baseline        | split + auto tier       | Verdict       |
|---------|------------------------|-------------------------|---------------|
| M1      | CPU raster, stuttery   | tier1_hw, smooth 60 FPS | win           |
| M2      | CPU raster, stuttery   | tier2_swiftshader or    | win           |
|         |                        | tier1_hw, smooth        |               |
| M3      | CPU raster, stuttery   | tier3_cpu, identical    | neutral (OK)  |

Config 3 (`DUPEZ_MAP_RENDERER=software`) on every machine must match the
inproc baseline. This is the safety valve for users who hit GPU driver
bugs — they can env-var their way back to the shipped behavior.

## Elevation path — install / uninstall

On each machine, exercise both B2a and B2b:

### B2a — runas
1. Fresh install, no scheduled task.
2. Launch `dupez.exe`, expect exactly one UAC prompt.
3. Verify helper PID runs at High IL (`Process Explorer` → Integrity).
4. Kill GUI → confirm helper dies within 2 seconds (parent watcher).
5. Kill helper → confirm GUI handles the lost pipe gracefully (reconnect
   on next op, new UAC prompt).

### B2b — scheduled_task
1. Fresh install, run once with `DUPEZ_ELEVATION=scheduled_task`.
2. Confirm one UAC prompt to register the task.
3. Exit and relaunch — expect ZERO UAC prompts on every subsequent run.
4. Verify `\DupeZ\FirewallHelper` task exists in Task Scheduler.
5. Kill GUI → confirm helper dies via parent-pid sentinel + watcher.
6. Uninstall flow: delete the task, confirm next launch prompts again.

## Launch failure modes

For each machine:

- Decline the UAC prompt → expect clear error toast, no crash, GUI
  stays up in "helper unavailable" mode, duping disabled, map still
  functional (tier3_cpu or better).
- Kill helper mid-duping → expect packet engine stops cleanly, no
  orphaned WinDivert handle, GUI reflects "disconnected", user can
  relaunch.
- Disconnect network cable mid-duping → behavior unchanged from baseline.

## Sign-off checklist

Before flipping the default from `inproc` to `split`:

- [ ] M1: configs 1, 2, 3, 4, 5, 6 all pass duping + hotkey tests
- [ ] M1: latency_regression.py shows no packet-path regression
- [ ] M2: configs 1, 2, 3, 4, 5, 6 all pass duping + hotkey tests
- [ ] M2: map fluidity improves from baseline
- [ ] M3: configs 1, 2, 3, 4, 5, 6 all pass duping + hotkey tests
- [ ] M3: map fluidity matches baseline (no regression)
- [ ] All three machines: B2a UAC-decline path recovers gracefully
- [ ] All three machines: B2b scheduled task registration works
- [ ] All three machines: helper crash-then-reconnect works
- [ ] No new Sentry-reported crashes in 1 week of beta
- [ ] ROADMAP.md updated with the flag flip date

Once every box is checked, flip the default in
`app/firewall_helper/feature_flag.py` and ship a point release.
