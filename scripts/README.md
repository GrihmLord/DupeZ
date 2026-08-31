# scripts/

Operational helpers and one-off diagnostics. Not part of the shipped
application — these are developer / support tools.

| File | Purpose |
| --- | --- |
| `release.ps1` | **Retired safety stub.** Refuses to tag or publish and points operators to the protected finalization, frozen/manual validation, draft staging, and publication sequence. |
| `defender_release_check.py` | Read-only Windows release check. Reports Authenticode status for `dist\DupeZ*.exe`, recent Defender detections, and optionally runs a Defender custom scan of `dist` with `--scan`. It never adds exclusions or changes Defender policy. |
| `reset_pytest_tmp.ps1` | **One-time pytest temp-dir ACL repair.** Pytest's default basetemp on Windows is `%LOCALAPPDATA%\Temp\pytest-of-<USER>`. If any prior pytest run was started from an elevated shell (or inherited UAC from `dupez.py`'s auto-elevation), that dir's DACL gets written admin-only, and every subsequent non-elevated run dies with `WinError 5 — Access is denied` at the `tmp_path` fixture. The long-term fix lives in `tests/conftest.py`, which pins basetemp to a repo-local `.pytest-tmp/` dir so the system-temp path is never touched again. This script does the one-time `takeown` + `icacls` + delete of the legacy orphan dir left behind by pre-fix runs. Run **once** from an elevated PowerShell: `.\scripts\reset_pytest_tmp.ps1`. |
| `sign-release.py` | Offline Ed25519 signer for the auto-update manifest. Generates the release keypair (`--gen-key`), signs `DupeZ_Setup.exe` into `.manifest.json` + `.manifest.sig` (`--sign`), and re-verifies an already-signed release (`--verify`). The private key never leaves the air-gapped signing host. |
| `vulnerability_review.py` | Reviews every exact runtime-lock version against PyPI's version-specific advisory API and writes the lock-bound release evidence. Responses must match the requested canonical name/version and contain a valid advisory list. Active findings fail the release build; finalization and staging accept only reviews generated within the preceding 24 hours (with at most five minutes of future clock skew). |
| `vex.py` | Converts actual active review findings into non-empty, vulnerability-specific OpenVEX statements. A clean review is the evidence for a clean release and intentionally produces no VEX document. |
| `hardware_evidence.py` · `redact_hardware_diagnostics.py` | Verifies native provenance and creates/validates privacy-safe hardware-smoke evidence only inside the repository's `Hardware Smoketest` GitHub Actions run. The job is restricted to `main` through the branch-limited `hardware-smoketest` environment, scopes target secrets only to authorization/test/redaction steps, installs pytest from `requirements-hardware-test-locked.txt` in a fresh per-run environment, and requires an RFC1918 IPv4 target inside an RFC1918 `/24`-or-narrower CIDR. It holds verified native bytes read-locked through the exact seven-test/four-file suite, fails closed if process enumeration is unavailable, and creates evidence only after exact-path cleanup. Raw output stays in a fresh private runner-temp tree, is removed before upload, and sanitized diagnostics upload only after an exact allowlist/hash verification succeeds; identifier-redacted failure artifacts are retained for seven days. |
| `validate_frozen_runtime.{ps1,py}` | Exercises both frozen Map profiles through real shortcuts, exact WebEngine/navigation/process proof, and verified cleanup. It read-locks the executable through each launch and writes 24-hour, session-bound private JSON. That unsigned JSON is operator evidence—not cryptographic provenance—and dirty engineering runs use a separate non-release filename. |
| `release_git_contract.ps1` | Shared fail-closed source-provenance boundary for finalization and release evidence consumers. It pins Git under Program Files, rejects inherited Git overrides/replacement refs/unsafe worktree configuration, force-checks tracked bytes and index state, and requires a clean attached branch. |
| `manual_release_gate_contract.ps1` · `frozen_runtime_evidence_contract.ps1` | Shared exact-schema consumers for the 16 manual walkthrough gates and per-run frozen lifecycle evidence. Staging uses the same contracts as evidence recording so missing, extra, stale, mismatched, or non-boolean claims fail closed. |
| `fix_webengine.bat` | Repair broken PyQt6 / PyQt6-WebEngine installs when the iZurvive map shows a placeholder. Wipes every PyQt6/Qt6 wheel, clears the pip cache, reinstalls the package set in a single resolver pass, and verifies `QWebEngineView` can actually import before exiting. |
| `diagnose_webengine.py` | Minimal smoke test that bypasses DupeZ entirely and opens iZurvive in a bare `QWebEngineView`. Prints every load event, renderer-process crash, and JS console message. Use when the map fails inside DupeZ to isolate whether the bug is in QtWebEngine itself or in DupeZ's wiring. |
| `sbom.py` · `sign-plugin.py` · `sign_models.py` · `lock-requirements.{ps1,sh}` · `relabel_episodes.py` · `report_findings.py` · `train_models.py` | Supply-chain + ML maintenance helpers — SBOM generation, whole-bundle plugin signing, model signing, requirements pinning, episode relabeling, findings reports, and model training. Plugin manifest v2 authenticates the exact path, size, and SHA-384 of every helper/resource; legacy entry-only plugins must be re-signed. Each tool is self-documenting via `--help`. |

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
