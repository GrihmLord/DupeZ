# Low-resource startup and crash resilience

DupeZ automatically applies a conservative startup profile when it detects any
of the following conditions:

- four or fewer logical CPU cores;
- eight GiB or less total physical memory; or
- two GiB or less currently available physical memory.

The profile does not disable DupeZ functionality. It defers the embedded DayZ
map's Chromium process until the map is opened, limits Qt's global worker pool,
shortens idle worker retention, replaces the splash-screen CPU spin with an
event-driven wait, and applies a bounded startup deadline.

## Operator overrides

These environment variables are intended for diagnostics and managed rollout:

| Variable | Values | Purpose |
|---|---|---|
| `DUPEZ_LOW_RESOURCE` | `auto`, `1`, `0` | Force or disable low-resource mode. |
| `DUPEZ_MAP_PREWARM` | `auto`, `1`, `0` | Force or disable Chromium map prewarm. |
| `DUPEZ_QT_MAX_THREADS` | `1`–`16` | Override the bounded Qt worker-pool size. |
| `DUPEZ_STARTUP_TIMEOUT_MS` | `30000`–`600000` | Override the startup watchdog deadline. |

Invalid values fall back to safe automatic defaults. The resolved profile is
logged using aggregate CPU and memory capacity only; it does not include device
identifiers, usernames, IP addresses, or file paths.

## Release validation matrix

A release candidate should be exercised in both GPU and Compat variants with:

1. `DUPEZ_LOW_RESOURCE=1` and `DUPEZ_MAP_PREWARM=0`;
2. automatic detection on a 4-core / 8-GiB Windows VM;
3. automatic detection on a normal-capacity Windows host;
4. launch, map-open, network-scan, disruption start/stop, hotkey, OBS overlay,
   account tracker, diagnostics, support bundle, sign-out, and clean shutdown;
5. repeated launch/close cycles while observing process count, handles, working
   set, and crash-dump output;
6. the complete unit, integration, frozen-startup, packaging, provenance,
   dependency-lock, Defender, and release-preflight gates.

Do not create a release tag from a source-only result. The signed GPU, Compat,
and installer artifacts must pass the repository's release preflight on the
approved Windows release machine.
