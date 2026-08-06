# CAPABILITY_MATRIX

| Capability | Status | Notes |
|---|---|---|
| Repository read/write | AVAILABLE | Full local workspace access |
| Python execution | AVAILABLE | .build-venv Python 3.11.9 |
| Automated tests | AVAILABLE | pytest installed in .build-venv |
| Dist preflight checks | AVAILABLE | Executed with blocking findings |
| Administrator-required scripts | BLOCKED | Current session non-elevated |
| Authenticode signing | BLOCKED | Signing material/tooling not configured in this session |
| Release publish (GitHub) | BLOCKED | Script requires main branch + clean tree + token |
| Corporate/legal/financial evidence | NOT_PROVIDED | Outside repo data room not supplied |
