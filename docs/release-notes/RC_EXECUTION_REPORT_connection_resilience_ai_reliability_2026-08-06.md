# RC Execution Report - connection_resilience_ai_reliability

Date: 2026-08-06
Source plan executed: docs/release-notes/RC_CHECKLIST_connection_resilience_ai_reliability_2026-08-06.md
Execution host: Windows, non-elevated PowerShell session

## 1) Scope and branch freeze
Status: PASS (with expected dirty branch)
- Captured full working tree delta for candidate branch.
- Verified release notes/checklist/commit-sequence artifacts are present.
- Branch is intentionally non-clean while preparing release candidate.

Evidence:
- git status --short
- docs/release-notes/RC_CHECKLIST_connection_resilience_ai_reliability_2026-08-06.md
- docs/release-notes/RELEASE_DELTA_connection_resilience_ai_reliability_2026-08-06.md
- docs/release-notes/COMMIT_SEQUENCE_connection_resilience_ai_reliability_2026-08-06.md

## 2) Capability and routing safety gates
Status: PASS
- pytest -q tests/test_clumsy_network_disruptor.py tests/test_direct_clumsy_manager.py tests/test_clumsy_engine_policy.py tests/test_disruption_presets.py
- Result: 121 passed

## 3) Bounded resilience behavior gates
Status: PASS
- Covered by routing/preset suite and full suite.
- No regression observed in bounded lag/expiry/validation paths.

## 4) AI and reliability hardening gates
Status: PASS
- Included in full-suite execution.
- Reliability and AI paths validated in full branch run.

## 5) Release and startup robustness
Status: PASS
- pytest -q tests/test_active_content_safety.py tests/test_gui_startup_smoke.py
- Result: 2 passed
- python scripts/release_preflight.py
- Result: Release preflight passed.

## 6) Full automated regression gate
Status: PASS
- pytest -q
- Result: 1293 passed, 8 skipped in 49.71s
- Skips are expected opt-in hardware and platform-conditioned checks.

## 7) Packaging and dist integrity (strict mode)
Status: PARTIAL / BLOCKED
Attempted checks:
- python scripts/release_preflight.py --dist --version 5.7.9
- Failed with concrete blockers:
  - missing dist/DupeZ_Setup.exe.manifest.json
  - missing dist/DupeZ_Setup.exe.manifest.sig
  - PyInstaller module unavailable in current interpreter for frozen-policy inspection
  - existing dist executables and installer not Authenticode signed (NotSigned)

Current dist inventory indicates stale/missing executable set for this session:
- present: DupeZ_Setup.exe, DupeZ_v5.7.9_Setup.exe, DupeZ.sbom.json, DupeZ.vex.json, binary-provenance.json
- missing now: DupeZ-GPU.exe, DupeZ-Compat.exe

## 8) Protected release flow scripts
Status: BLOCKED BY POLICY/PRIVILEGE (expected)
- scripts/finalize_release.ps1 -Version 5.7.9 -AllowNonMainValidation -AllowUnsigned
  - blocked: requires Administrator PowerShell
- scripts/validate_frozen_runtime.ps1 -Variant GPU
  - blocked: dist/DupeZ-GPU.exe missing
- scripts/stage_release.ps1 -Mode Draft -Version 5.7.9
  - blocked: must run from main branch and clean repo state

## 9) Required unblock sequence to complete plan fully
Run these in order on the protected signing host:
1. Open Administrator PowerShell.
2. Rebuild exact artifacts:
   - cmd /c packaging\build_variants.bat
3. Verify dist now includes:
   - DupeZ-GPU.exe
   - DupeZ-Compat.exe
   - DupeZ_v5.7.9_Setup.exe
4. Sign artifacts (configure DUPEZ_SIGN_CERT and signtool prerequisites).
5. Run strict preflight:
   - .build-venv\Scripts\python.exe scripts\release_preflight.py --dist --version 5.7.9
6. Run frozen runtime validators:
   - non-admin desktop session: powershell -File scripts\validate_frozen_runtime.ps1 -Variant GPU
   - admin session: powershell -File scripts\validate_frozen_runtime.ps1 -Variant Compat
7. Record manual release validation:
   - powershell -File scripts\record_manual_release_validation.ps1 -Version 5.7.9
8. On main branch with clean tree and GH token:
   - powershell -File scripts\stage_release.ps1 -Mode Draft -Version 5.7.9
   - powershell -File scripts\stage_release.ps1 -Mode Publish -Version 5.7.9

## 10) Overall readiness verdict
- Engineering regression quality: READY (all automated branch gates green).
- Public release cut readiness: NOT READY until signing, strict dist preflight, frozen runtime evidence, manual validation evidence, and main-branch clean staging gates are completed.
