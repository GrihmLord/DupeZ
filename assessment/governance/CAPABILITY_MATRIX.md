# CAPABILITY_MATRIX

| Capability | Status | Notes |
|---|---|---|
| Repository read/write | AVAILABLE | Full local workspace access |
| Python execution | AVAILABLE | Source validation uses .venv Python 3.11 |
| Automated tests | AVAILABLE | 1326 passed; 8 expected opt-in/platform skips |
| Hermetic packaging | AVAILABLE | Policy recreates .release-venv from the hashed lock |
| Dist preflight checks | AVAILABLE | Source pass; exact v5.8.0 dist evidence pending |
| Administrator-required scripts | AVAILABLE | Required only after clean merge to main |
| Authenticode signing | CONDITIONAL | Explicit unsigned public route is supported and disclosed |
| Release publish (GitHub) | AVAILABLE | Protected draft/hash verification precedes publish |
| Corporate/legal/financial evidence | NOT_PROVIDED | Outside repo data room not supplied |
