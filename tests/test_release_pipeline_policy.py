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

    assert '#define MyAppVersion   "5.7.9"' in installer
    assert "CloseApplications=yes" in installer
    assert (
        "CloseApplicationsFilter=dupez.exe,DupeZ-GPU.exe,DupeZ-Compat.exe"
        in installer
    )
    assert "RestartApplications=no" in installer
    assert "taskkill" not in installer.lower()
    assert "PrepareToInstall" not in installer
    assert "dupez_helper.exe" not in installer.lower()


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


def test_release_staging_refuses_published_asset_replacement():
    script = _read("scripts/stage_release.ps1")

    assert "scripts\\release_preflight.py" in script
    assert "--dist" in script
    assert "SHA256SUMS.txt" in script
    assert "already published" in script
    assert "immutable assets will not be replaced" in script
    assert '"--draft"' in script
    assert '"--draft=false"' in script
    assert 'ValidateSet("Draft", "Publish")' in script


def test_release_workflow_keeps_keys_on_protected_self_hosted_runner():
    workflow = _read(".github/workflows/release.yml")

    assert "runs-on: [self-hosted, windows, release-signing]" in workflow
    assert "environment: production-release" in workflow
    assert "github.ref_name" in workflow and "main" in workflow
    assert "scripts\\finalize_release.ps1" in workflow
    assert "scripts\\stage_release.ps1" in workflow
    assert "dist\\DupeZ-GPU.exe" in workflow
    assert "dist\\DupeZ-Compat.exe" in workflow
    assert workflow.count("--verify-runtime-imports") == 1
    assert "secrets.DUPEZ_SIGN_CERT" not in workflow
    assert "secrets.DUPEZ_SIGN_PRIVKEY" not in workflow
    assert "contents: write" in workflow


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
