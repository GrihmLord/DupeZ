"""Static and parser-level policy tests for v5.7.9 release finalization."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_installer_uses_restart_manager_without_force_kill_hook():
    installer = _read("packaging/installer.iss")
    lowered = installer.lower()

    assert '#define MyAppVersion   "5.7.9"' in installer
    assert "CloseApplications=yes" in installer
    assert (
        "CloseApplicationsFilter=dupez.exe,DupeZ-GPU.exe,DupeZ-Compat.exe"
        in installer
    )
    assert "RestartApplications=no" in installer
    assert "[code]" not in lowered
    assert "preparetoinstall" not in lowered
    assert "taskkill.exe" not in lowered
    assert "'/im'" not in lowered and '"/im"' not in lowered
    assert "dupez_helper.exe" not in lowered


def test_release_finalizer_requires_real_signing_and_security_gates():
    script = _read("scripts/finalize_release.ps1")

    required = (
        "DUPEZ_SIGN_CERT",
        "DUPEZ_SIGN_PRIVKEY",
        "Windows SDK SignTool",
        "Inno Setup ISCC.exe",
        "Get-AuthenticodeSignature",
        "TimeStamperCertificate",
        "Get-MpComputerStatus",
        "Update-MpSignature",
        "-DisableRemediation",
        "-ReturnHR",
        "scripts\\release_preflight.py",
        "--dist",
        "SHA256SUMS.txt",
        "release-attestation.json",
        "4e9c3c6731efbaa8",
    )
    for token in required:
        assert token in script, token

    assert "Add-MpPreference" not in script
    assert "Set-MpPreference" not in script
    assert "DisableRealtimeMonitoring" not in script
    assert "--gen-key" not in script


def test_release_staging_requires_exact_artifact_evidence():
    script = _read("scripts/stage_release.ps1")

    required = (
        "scripts\\release_preflight.py",
        "--dist",
        "SHA256SUMS.txt",
        "frozen-runtime-evidence-gpu.json",
        "frozen-runtime-evidence-compat.json",
        "manual-release-validation.json",
        "dupez.frozen-runtime-validation.v1",
        "dupez.manual-release-validation.v1",
        "release-validation-attestation.json",
        "split-medium-integrity-gui",
        "inproc-high-integrity",
        "already published",
        "immutable assets will not be replaced",
        '"--draft"',
        '"--draft=false"',
        'ValidateSet("Draft", "Publish")',
    )
    for token in required:
        assert token in script, token


def test_release_workflow_keeps_keys_on_protected_nonpublishing_runner():
    workflow = _read(".github/workflows/release.yml")

    assert "runs-on: [self-hosted, windows, release-signing]" in workflow
    assert "environment: production-release" in workflow
    assert "github.ref_name" in workflow and "main" in workflow
    assert "scripts\\finalize_release.ps1" in workflow
    assert "scripts\\stage_release.ps1" not in workflow
    assert "dist\\DupeZ-GPU.exe" in workflow
    assert "dist\\DupeZ-Compat.exe" in workflow
    assert workflow.count("--verify-runtime-imports") == 1
    assert "secrets.DUPEZ_SIGN_CERT" not in workflow
    assert "secrets.DUPEZ_SIGN_PRIVKEY" not in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "release create" not in workflow
    assert "release edit" not in workflow


def test_frozen_runtime_validator_enforces_architecture_and_real_shortcuts():
    script = _read("scripts/validate_frozen_runtime.ps1")

    required = (
        'ValidateSet("GPU", "Compat")',
        "GPU validation must run from a standard, non-Administrator",
        "Compat validation must run from Administrator PowerShell",
        "DUPEZ_LOW_RESOURCE",
        "DUPEZ_MAP_PREWARM",
        "DupeZ started successfully",
        "Map: lazy DayZMapGUI initialized on first tab open",
        "SendCtrlKey($dashboard, 0x32)",
        "SendCtrlKey($dashboard, 0x51)",
        "frozen-runtime-evidence-",
        "split-medium-integrity-gui",
        "inproc-high-integrity",
    )
    for token in required:
        assert token in script, token


def test_manual_recorder_requires_all_exact_artifact_gates():
    script = _read("scripts/record_manual_release_validation.ps1")

    required = (
        "dupez.operator-acknowledgement.v1",
        "frozen-runtime-evidence-gpu.json",
        "frozen-runtime-evidence-compat.json",
        "hidden_clumsy_no_flash",
        "gpu_diagnostic_restore",
        "compat_diagnostic_restore",
        "map_failure_retry",
        "installer_fresh_install",
        "installer_upgrade",
        "installer_uninstall",
        "manual-release-validation.json",
        "Type YES for each gate",
    )
    for token in required:
        assert token in script, token


def test_hardware_workflow_includes_full_and_hidden_clumsy_gates():
    workflow = _read(".github/workflows/hardware-smoketest.yml")

    assert "tests/test_clumsy_full_controls_hardware.py" in workflow
    assert "tests/test_clumsy_hidden_window_hardware.py" in workflow
    assert "DUPEZ_SMOKETEST_FULL_TIMER_SECONDS: '4'" in workflow
    assert "Assert no owned Clumsy process leaked" in workflow


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell parser is Windows-only")
@pytest.mark.parametrize(
    "relative",
    (
        "scripts/finalize_release.ps1",
        "scripts/validate_frozen_runtime.ps1",
        "scripts/record_manual_release_validation.ps1",
        "scripts/stage_release.ps1",
    ),
)
def test_release_powershell_scripts_parse_under_windows_powershell(relative):
    powershell = Path(
        os.environ.get("WINDIR", r"C:\Windows")
    ) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    assert powershell.is_file()
    path = (ROOT / relative).resolve()
    escaped = str(path).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
