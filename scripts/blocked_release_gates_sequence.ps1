#requires -Version 5.1
<#
Run only the blocked release gates in strict sequence for DupeZ.

This script is intentionally phase-driven because the protected flow spans both
Administrator and standard desktop sessions:
- finalize_release.ps1 requires Administrator PowerShell.
- validate_frozen_runtime.ps1 requires GPU in non-admin and Compat in admin.
- stage_release.ps1 requires main + clean tree + GH token.
#>

[CmdletBinding()]
param(
    [ValidateSet("admin-finalize", "gpu-validate", "admin-compat", "admin-stage-draft", "admin-stage-publish")]
    [string]$Phase,

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.8.0",

    [string]$Operator = "",

    [switch]$AllowUnsigned,

    [switch]$AllowNonMainValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Test-IsAdmin {
    return (
        New-Object Security.Principal.WindowsPrincipal(
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-MainClean {
    $git = (Get-Command git -ErrorAction Stop).Source
    $branch = (& $git branch --show-current).Trim()
    if (-not $AllowNonMainValidation -and $branch -ne "main") {
        throw "Phase requires main branch. Current branch: $branch"
    }
    if (@(& $git status --porcelain).Count -ne 0) {
        & $git status --short
        throw "Phase requires a clean working tree."
    }
}

function Run-Checked {
    param([string]$Name, [scriptblock]$Action)
    Write-Host "`n=== $Name ==="
    & $Action
}

switch ($Phase) {
    "admin-finalize" {
        if (-not (Test-IsAdmin)) {
            throw "admin-finalize must run in Administrator PowerShell."
        }
        Assert-MainClean
        $args = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            "scripts/finalize_release.ps1", "-Version", $Version
        )
        if ($AllowUnsigned) { $args += "-AllowUnsigned" }
        if ($AllowNonMainValidation) { $args += "-AllowNonMainValidation" }
        Run-Checked -Name "FINALIZE RELEASE" -Action { powershell @args }
        Write-Host "admin-finalize complete. Next run gpu-validate in NON-admin desktop session."
    }

    "gpu-validate" {
        if (Test-IsAdmin) {
            throw "gpu-validate must run in NON-admin desktop PowerShell."
        }
        Assert-MainClean
        Run-Checked -Name "GPU FROZEN VALIDATION" -Action {
            powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validate_frozen_runtime.ps1 -Variant GPU
        }
        Write-Host "gpu-validate complete. Next run admin-compat in Administrator PowerShell."
    }

    "admin-compat" {
        if (-not (Test-IsAdmin)) {
            throw "admin-compat must run in Administrator PowerShell."
        }
        Assert-MainClean
        Run-Checked -Name "COMPAT FROZEN VALIDATION" -Action {
            powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validate_frozen_runtime.ps1 -Variant Compat
        }
        if ([string]::IsNullOrWhiteSpace($Operator)) {
            throw "Provide -Operator for manual validation recording (e.g. -Operator GrihmLord)."
        }
        Run-Checked -Name "RECORD MANUAL RELEASE VALIDATION" -Action {
            powershell -NoProfile -ExecutionPolicy Bypass -File scripts/record_manual_release_validation.ps1 -Version $Version -Operator $Operator
        }
        Write-Host "admin-compat complete. Next run admin-stage-draft (and optionally admin-stage-publish)."
    }

    "admin-stage-draft" {
        if (-not (Test-IsAdmin)) {
            throw "admin-stage-draft must run in Administrator PowerShell."
        }
        Assert-MainClean
        if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and [string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
            throw "GITHUB_TOKEN or GH_TOKEN is required for staging."
        }
        Run-Checked -Name "STAGE DRAFT RELEASE" -Action {
            powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stage_release.ps1 -Mode Draft -Version $Version
        }
        Write-Host "admin-stage-draft complete. Next run admin-stage-publish when ready."
    }

    "admin-stage-publish" {
        if (-not (Test-IsAdmin)) {
            throw "admin-stage-publish must run in Administrator PowerShell."
        }
        Assert-MainClean
        if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and [string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
            throw "GITHUB_TOKEN or GH_TOKEN is required for publish."
        }
        Run-Checked -Name "PUBLISH STAGED RELEASE" -Action {
            powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stage_release.ps1 -Mode Publish -Version $Version
        }
        Write-Host "admin-stage-publish complete. All blocked release gates finished."
    }
}
