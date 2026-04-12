# DupeZ v5.3.0 — Split-Elevation Architecture + Hardware Map + Preset Collapse

First release shipping **two user-facing binaries from one codebase**:

- **`DupeZ-GPU.exe`** — asInvoker, split-arch, hardware-rasterized iZurvive map. **Recommended default.**
- **`DupeZ-Compat.exe`** — requireAdministrator, legacy inproc, CPU-raster fallback. Use this if the GPU variant misbehaves on a blocklisted GPU, ancient drivers, or locked-down corporate environments.

Lands ADR-0001 end-to-end: Medium-IL GUI + elevated helper over IPC, helper-role dispatch reusing the same frozen exe, feature-flag routing in the firewall layer, a renderer tier resolver, collapses the preset taxonomy from 8 entries to 5, reorganizes packaging files into a dedicated `packaging/` subtree, beefs up scanner hostname resolution to a 4-stage fallback chain, and bundles zeroconf for real mDNS discovery out of the box.

---

## Highlights

### Split-Elevation Architecture (ADR-0001)
- GUI runs at Medium IL so Chromium GPU init works for the embedded iZurvive map.
- Firewall + WinDivert ops forwarded to an elevated helper over IPC.
- Helper is the **same frozen exe** re-invoked with `--role helper --parent-pid N`. Dispatched before any `app.*` / PyQt6 import so it never boots the GUI, eliminating the infinite admin-spawn loop.
- Feature-flag routing in `app/firewall/blocker.py` transparently forwards `block_device`, `unblock_device`, `is_ip_blocked`, `clear_all_dupez_blocks`, and `get_blocked_ips` under split mode. Inproc path unchanged.
- Split-aware splash screen defers the WinDivert engine check and reports `WinDivert engine: deferred (split mode — helper owns engine)` instead of the old red "unavailable" line.

### Hardware-Rasterized Map
- New `app/gui/map_host/renderer_tier.py` picks `tier1_hw` / `tier2_swiftshader` / `tier3_cpu` based on `DUPEZ_MAP_RENDERER` + a best-effort GPU probe.
- Matching Chromium flags applied before any PyQt6 import.
- "Open in Browser ↗" tooltip reports which tier is active.
- `AA_ShareOpenGLContexts` application attribute set on `QCoreApplication` before `QApplication` so Qt 6 WebEngine + GL-adjacent widgets coexist cleanly.

### Preset Taxonomy Collapse (8 → 5)
Final set: **Red Disconnect · Lag · God Mode · Dupe Mode · Custom**.

- `Heavy Lag` and `Light Lag` merged into a single `Lag` preset — tune intensity via the Lag Delay / Drop % sliders (Light ≈ 800ms / 60%, Heavy ≈ 3000ms / 95%).
- `God Mode Aggressive` removed — covered by the existing God Mode sliders.
- `Desync` removed — rarely used, covered by Custom.

### Dual-Variant Build Pipeline
- `packaging/build_variants.bat` is the new canonical release driver.
- Both specs (`dupez_gpu.spec` + `dupez_compat.spec`) share `packaging/build_common.py`, which writes a per-variant `_build_default.py` before Analysis, baking in the compiled-in `DUPEZ_ARCH` default.
- No env var required at runtime — the variant you download is the variant you get.

### 4-Stage Hostname Resolution
Order in `app/network/enhanced_scanner.py`:

1. `socket.gethostbyaddr`
2. `socket.getfqdn`
3. NetBIOS (`nbtstat -a`)
4. mDNS via bundled zeroconf
5. Synthesized `<vendor>-<mac_suffix>` fallback (or `device-<ip>` if vendor unknown)

The GUI Hostname column is **never blank or "Unknown"** again. `app/network/device_scan.py` and `app/core/state.py` also defensively synthesize on inbound dicts with missing hostnames.

### Packaging Reorganization
All build artifacts now live under `packaging/`:

```
packaging/
├── build.bat
├── build_common.py
├── build_variants.bat        # ← canonical release driver
├── dupez.manifest
├── dupez.spec                # legacy single-binary
├── dupez_compat.manifest
├── dupez_compat.spec         # NEW — Compat variant
├── dupez_gpu.spec            # NEW — GPU variant
├── installer.iss
└── version_info.py
```

Spec files use `HERE = os.path.dirname(SPEC)` + `ROOT = HERE/..` for path resolution. Inno Setup uses `SourceDir=..` so all existing `Source:` paths resolve from repo root. Batch drivers `pushd "%~dp0.."` before running anything.

---

## Fixed

- **Infinite admin-spawn loop** when `DupeZ-GPU.exe --role helper` re-launched the GUI instead of dispatching to the helper module. Root cause: `_maybe_dispatch_helper_role()` ran too late. Fixed by dispatching at the top of `dupez.py` before any other import.
- **Chromium GPU init deadlock under admin token** (legacy inproc). Pre-existing workaround (`--no-sandbox --disable-gpu`) now only applied when the tier resolver reports `tier3_cpu`; split mode gets real hardware raster.
- **`plugins/example_ping_monitor/plugin.py`** missing `typing.Any` import.
- **`packaging/build.bat` final line truncation** (pre-existing) — was cut off mid-word with no `popd` / `endlocal` / `pause`. Fixed.
- **Splash log noise** — no more scary red "WinDivert engine: unavailable" lines at Medium IL startup.

---

## Migration Notes

- **Two binaries now ship per release.** `DupeZ-GPU.exe` is the recommended default. `DupeZ-Compat.exe` is the fallback for machines where split-mode IPC or WebEngine hardware raster misbehaves. The installer bundles both.
- **Preset UI shows 5 entries instead of 8** — muscle-memory translations:
  - `Heavy Lag` / `Light Lag` → `Lag` (tune via sliders)
  - `God Mode Aggressive` → `God Mode` (tune via sliders)
  - `Desync` → `Custom`
- **No settings file migration required.** `%APPDATA%\DupeZ` schema is unchanged from v5.2.4.
- **`zeroconf` is a new hard dependency** if you `pip install -r requirements.txt` from source. No action needed for installer users — it's bundled in both frozen exes.
- **Upgrading from v5.2.0–v5.2.3** (x86 install path): uninstall first, then install v5.3.0. Upgrading from v5.2.4 (x64 install path): in-place upgrade works, settings preserved.

---

## Packaging / Repo Hygiene

- Root cleanup: deleted `FATAL_CRASH.txt`, `crash-trace.txt`, `launch_error.txt`, stray `query` file, `__pycache__/`, `.pytest_cache/`. `.gitignore` now covers the transient crash-dump patterns.
- Previously-planned v5.3.0 (GUI integration for engine features) has been deferred to v5.5.0. See `ROADMAP.md`.

---

## Downloads

- **`DupeZ-GPU.exe`** — recommended single-binary download
- **`DupeZ-Compat.exe`** — fallback single-binary download
- **`DupeZ_v5.3.0_Setup.exe`** — Windows installer (bundles both variants, Add/Remove Programs integration, Start Menu shortcuts)

---

Full change history: [`CHANGELOG.md`](https://github.com/GrihmLord/DupeZ/blob/v5.3.0/CHANGELOG.md)

Got a feature request or bug report? [Open an issue](https://github.com/GrihmLord/DupeZ/issues).
