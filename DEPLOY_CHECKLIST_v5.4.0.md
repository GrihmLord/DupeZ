# Deploy Checklist: DupeZ v5.4.0
**Date:** 2026-04-12 | **Deployer:** GrihmLord

---

## Pre-Deploy

- [x] All code committed and pushed to `feature/windivert-forward-layer`
- [x] Version bumped in all 8 locations (`__version__.py`, `version_info.py`, `installer.iss`, `dupez.manifest`, `dupez_compat.manifest`, `build.bat`, `build_variants.bat`, `README.md`)
- [x] CHANGELOG.md updated with v5.4.0 section
- [x] Release notes created (`docs/release-notes/RELEASE_NOTES_5.4.0.md`)
- [x] No known critical bugs in release
- [x] Python syntax verified on all modified files (`ast.parse()` passed)
- [ ] Manual smoke test on Windows — launch DupeZ-GPU.exe, verify dashboard loads
- [ ] Manual smoke test — Account Tracker: add, edit, duplicate, delete, search, filter chips, context menu, bulk ops, import XLSX, export XLSX
- [ ] Manual smoke test — theme switching: dark → light → hacker → rainbow (verify nav buttons don't break)
- [ ] Manual smoke test — About dialog: verify ARCH row shows "Split", version shows v5.4.0
- [ ] Manual smoke test — Help panel: spot-check 2-3 sections for accuracy
- [ ] Manual smoke test — Clumsy Control: verify device panel splitter can't collapse below 320px
- [ ] Rollback plan documented (see below)

## Build

- [x] `build_variants.bat` ran successfully — DupeZ-GPU.exe built
- [x] `build_variants.bat` ran successfully — DupeZ-Compat.exe built
- [x] `_build_default.py` correctly wrote `split` for GPU variant, `inproc` for Compat variant
- [ ] Inno Setup installer built — `DupeZ_v5.4.0_Setup.exe` produced
- [ ] Installer tested — silent install, uninstall, upgrade from v5.3.0

## Deploy (GitHub Release)

- [x] Tag `v5.4.0` created and pushed
- [x] GitHub release created at https://github.com/GrihmLord/DupeZ/releases/tag/v5.4.0
- [x] `DupeZ-GPU.exe` attached to release
- [x] `DupeZ-Compat.exe` attached to release
- [ ] `DupeZ_v5.4.0_Setup.exe` attached to release (pending Inno Setup build)
- [ ] Release notes body matches `RELEASE_NOTES_5.4.0.md`
- [ ] Download links work — test download of each binary

## Post-Deploy

- [ ] Download v5.4.0 from GitHub release page and verify it launches
- [ ] Auto-updater test — run v5.3.0, verify it detects v5.4.0 and offers update
- [ ] Confirm release page looks correct (title, body, assets)
- [ ] Root file cleanup committed (move audit report + release notes to `docs/`)
- [ ] Close related issues (if any)

## Rollback Plan

**Trigger:** If v5.4.0 binaries crash on launch, corrupt saved accounts, or the auto-updater serves a broken build.

**Steps:**
1. Delete the v5.4.0 release on GitHub (or mark as pre-release)
2. Remove the `v5.4.0` tag: `git tag -d v5.4.0 && git push origin :refs/tags/v5.4.0`
3. Users on v5.3.0 will not be offered the update
4. Users who already updated can download v5.3.0 from the releases page manually
5. Fix the issue on `feature/windivert-forward-layer`, re-tag, re-release

**Data safety:** Account data is stored in `%APPDATA%\DupeZ` JSON files. v5.4.0 only adds the `notes` field (backfilled as empty string). Rolling back to v5.3.0 is safe — the extra field is silently ignored by the older version.

---

*Checklist items marked [x] have been verified during this session.*
