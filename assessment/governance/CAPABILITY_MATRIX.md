# CAPABILITY_MATRIX

| Capability | Status | Notes |
|---|---|---|
| Repository read/write | AVAILABLE | Full local workspace access |
| Python execution | AVAILABLE | Full tests and CI-equivalent source gate ran on CPython 3.13.14 x64. Local `.venv` and existing `.release-venv` are 3.11.9; the latter is stale/noncanonical and canonical builds must recreate it with 3.13.14. |
| Automated tests | AVAILABLE | 2110 passed; 10 expected skips (3 opt-in Clumsy hardware, 3 symlink-privilege redactor, 3 opt-in hardware-smoketest, 1 installer symlink); 53.02% coverage; 133.77s |
| Hermetic packaging | AVAILABLE | Policy recreates .release-venv from the hashed lock |
| Dist preflight checks | AVAILABLE | Source pass; exact v5.8.0 dist evidence pending |
| Administrator-required scripts | CONDITIONAL | Run only after server-side governance is configured and source is merged cleanly to main |
| Authenticode signing | CONDITIONAL | Standard staged-child signing is implemented; certificate/host inputs are external |
| Release publish (GitHub) | BLOCKED | Read-only API inspection found `main` and `production-release` unprotected; workflow-local guards are defense in depth only |
| Corporate/legal/financial evidence | NOT_PROVIDED | Outside repo data room not supplied |
