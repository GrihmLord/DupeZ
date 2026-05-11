# DupeZ v5.6.3 — Crash-Safety + Duping Audit Hardening

Tightens the process-level crash-safety story across the full launch path. Driven by a deep audit of the duping subsystem (Red Disconnect / clumsy / netcut-style ARP) that confirmed the hot path is solid — but found three latent failure modes around C-extension crashes, helper death recovery, and split-mode shutdown. Also fixes documentation drift and a dead taskkill in the build script.

## Added

- **`faulthandler` enabled at process entry (`dupez.py`).** Installs a signal handler that dumps a Python-level stack to stderr from the C crash path. `sys.excepthook` only catches Python exceptions; when WinDivert.dll, Qt6Core.dll, or Chromium's GPU process segfaults, the process previously died with no traceback at all. Now the crash leaves a usable trace.

## Fixed

- **Pipe-disconnect stuck state in `DisruptionManagerProxy._call` (`app/firewall_helper/ipc_client.py`).** When the elevated helper crashed mid-session, the proxy's `_connected` flag stayed True forever — every subsequent `disrupt_device()` call returned False silently with no recovery path. `_call` now catches `(ConnectionError, OSError, BrokenPipeError)`, closes the dead client, resets `_connected=False` and `_helper_spawn_attempted=False`, then re-raises so the next call re-spawns the helper cleanly.
- **`_shutdown_cleanup` bypassed the feature-flag factory (`app/main.py`).** Imported `disruption_manager` directly, which under `DUPEZ_ARCH=split` is the in-process singleton — *not* the real engine running in the elevated helper. Result: split-mode shutdown was a silent no-op and could leave packet filters live across app restarts. Now uses `get_disruption_manager()` so split mode tears down via IPC; inproc behaviour unchanged.
- **Stale "95% drop" doc in Red Disconnect help (`app/gui/panels/help_panel.py`).** Two locations referenced the legacy 95% drop value; the actual preset has shipped at 100% drop since the disconnect-module rewrite. Updated to match runtime behavior.
- **Dead `taskkill /f /im dupez_helper.exe` in build script (`packaging/build_variants.bat`).** No separate helper exe is built — the elevated helper is `DupeZ-GPU.exe` re-invoked with `--role helper`. Removed the no-op kill and replaced with a clarifying comment so future maintainers don't reintroduce a separate helper binary by mistake.

## Downloads

- **`DupeZ_v5.6.3_Setup.exe`** — Inno Setup installer (recommended).
- **`DupeZ-GPU.exe`** — portable, asInvoker manifest, split-mode architecture, GPU map. Default for most users.
- **`DupeZ-Compat.exe`** — portable, requireAdministrator manifest, in-process engine. For environments where Chromium's GPU process won't initialize (blocklisted GPUs, restricted desktops).

## Test plan

- Build both variants: `packaging\build_variants.bat`. Verify `dist\DupeZ-GPU.exe` and `dist\DupeZ-Compat.exe` are produced and version stamp shows 5.6.3.0.
- Smoke-launch GPU variant on a Win11 box with a discrete GPU. Confirm Medium-IL launch, helper spawns on first DISRUPT, Red Disconnect lands.
- Smoke-launch Compat variant on a Win10 box with no GPU. Confirm self-elevation, inproc engine starts.
- Force a helper kill mid-disruption: `taskkill /f /im DupeZ-GPU.exe` against the elevated child. Next DISRUPT click should re-spawn the helper, not fail silently.
- Verify FATAL_CRASH.txt contains a scrubbed traceback if you induce a hard crash via debug menu.
