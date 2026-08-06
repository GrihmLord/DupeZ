# Blocked Release Gates Runbook (v5.7.9)

This runbook resolves the three currently blocked gates in strict order:
1. Admin-required protected finalization flow.
2. Main-branch + clean-tree staging prerequisite.
3. Dist preflight/signing/sidecar readiness through protected scripts.

## Preconditions
- Branch: `main`
- Working tree: clean (`git status --porcelain` empty)
- Required environment: signing/updater keys as expected by `scripts/finalize_release.ps1`
- GitHub auth: `GITHUB_TOKEN` or `GH_TOKEN`

## Exact sequence

### One-command mode (recommended)
Run this repeatedly until all phases are DONE:
```cmd
scripts\release_gate_launcher.cmd
```

The launcher tracks state in `dist/blocked-release-gates-progress.json`, auto-elevates admin phases, and tells you when a non-admin window is required.

Useful commands:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_gate_launcher.ps1 -Phase status -Version 5.7.9
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_gate_launcher.ps1 -Phase reset -Version 5.7.9
```

### A) Administrator PowerShell
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-finalize -Version 5.7.9
```

### B) Standard (non-admin) desktop PowerShell
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase gpu-validate -Version 5.7.9
```

### C) Administrator PowerShell
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-compat -Version 5.7.9 -Operator <YOUR_NAME>
```

### D) Administrator PowerShell (draft)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-draft -Version 5.7.9
```

### E) Administrator PowerShell (publish)
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/blocked_release_gates_sequence.ps1 -Phase admin-stage-publish -Version 5.7.9
```

## Expected outputs
- `dist/release-attestation.json`
- `dist/release-validation-attestation.json`
- `dist/manual-release-validation.json`
- `dist/frozen-runtime-evidence-gpu.json`
- `dist/frozen-runtime-evidence-compat.json`
- Draft/published GitHub release with verified asset hashes
