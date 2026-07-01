# scripts/

Operational helpers and one-off diagnostics. Not part of the shipped
application — these are developer / support tools.

| File | Purpose |
| --- | --- |
| `release.ps1` | **Release driver with fail-fast guards.** Runs the full build → branch → commit → PR → merge → tag → GitHub-release sequence, checking `$LASTEXITCODE` after every step and aborting on the first failure — before anything irreversible. Verifies the commit actually landed (HEAD moved, tree clean) and that the tag dereferences to the merged commit. Replaces the hand-typed sequence that silently mis-tagged four releases when a pre-commit hook ate the commit. Usage: `.\scripts\release.ps1 -Version 5.7.4`. |
| `defender_release_check.py` | Read-only Windows release check. Reports Authenticode status for `dist\DupeZ*.exe`, recent Defender detections, and optionally runs a Defender custom scan of `dist` with `--scan`. It never adds exclusions or changes Defender policy. |
| `reset_pytest_tmp.ps1` | **One-time pytest temp-dir ACL repair.** Pytest's default basetemp on Windows is `%LOCALAPPDATA%\Temp\pytest-of-<USER>`. If any prior pytest run was started from an elevated shell (or inherited UAC from `dupez.py`'s auto-elevation), that dir's DACL gets written admin-only, and every subsequent non-elevated run dies with `WinError 5 — Access is denied` at the `tmp_path` fixture. The long-term fix lives in `tests/conftest.py`, which pins basetemp to a repo-local `.pytest-tmp/` dir so the system-temp path is never touched again. This script does the one-time `takeown` + `icacls` + delete of the legacy orphan dir left behind by pre-fix runs. Run **once** from an elevated PowerShell: `.\scripts\reset_pytest_tmp.ps1`. |
| `sign-release.py` | Offline Ed25519 signer for the auto-update manifest. Generates the release keypair (`--gen-key`), signs `DupeZ_Setup.exe` into `.manifest.json` + `.manifest.sig` (`--sign`), and re-verifies an already-signed release (`--verify`). The private key never leaves the air-gapped signing host. |
| `fix_webengine.bat` | Repair broken PyQt6 / PyQt6-WebEngine installs when the iZurvive map shows a placeholder. Wipes every PyQt6/Qt6 wheel, clears the pip cache, reinstalls the package set in a single resolver pass, and verifies `QWebEngineView` can actually import before exiting. |
| `diagnose_webengine.py` | Minimal smoke test that bypasses DupeZ entirely and opens iZurvive in a bare `QWebEngineView`. Prints every load event, renderer-process crash, and JS console message. Use when the map fails inside DupeZ to isolate whether the bug is in QtWebEngine itself or in DupeZ's wiring. |
| `sbom.py` · `sign-plugin.py` · `sign_models.py` · `lock-requirements.{ps1,sh}` · `relabel_episodes.py` · `report_findings.py` · `train_models.py` | Supply-chain + ML maintenance helpers — SBOM generation, plugin / model signing, requirements pinning, episode relabeling, findings reports, and model training. Each is self-documenting via `--help`. |

## Usage

Both scripts assume they are run from the DupeZ repo root (so relative
module imports resolve), not from inside `scripts/`.

```powershell
cd C:\path\to\DupeZ

# Repair QtWebEngine install
.\scripts\fix_webengine.bat

# Smoke-test QtWebEngine against iZurvive
python scripts\diagnose_webengine.py
```
