# SYSTEM_INVENTORY

- Primary language: Python
- Primary UI stack: PyQt6
- Packaging: PyInstaller + Inno Setup
- Test framework: pytest
- Release scripts: scripts/finalize_release.ps1, scripts/validate_frozen_runtime.ps1, scripts/stage_release.ps1
- Distribution artifacts: GPU/Compat executables and setup installer variants
- Security-adjacent capabilities: network-adjacent controls under app/firewall and driver-integrated flows
