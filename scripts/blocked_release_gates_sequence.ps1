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
. (Join-Path $PSScriptRoot "release_git_contract.ps1")

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Resolve-InboxWindowsPowerShell {
    $systemDirectory = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::System
    )
    if (
        [string]::IsNullOrWhiteSpace($systemDirectory) -or
        -not [IO.Path]::IsPathRooted($systemDirectory)
    ) {
        throw "Could not resolve the absolute Windows system directory."
    }

    $candidate = [IO.Path]::GetFullPath((
        Join-Path $systemDirectory "WindowsPowerShell\v1.0\powershell.exe"
    ))
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Inbox Windows PowerShell executable is missing."
    }

    $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    if (
        -not [IO.Path]::IsPathRooted($resolved) -or
        -not [string]::Equals(
            $resolved,
            $candidate,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Inbox Windows PowerShell executable resolved unexpectedly."
    }
    return $resolved
}

$inboxWindowsPowerShell = Resolve-InboxWindowsPowerShell

function Test-IsAdmin {
    return (
        New-Object Security.Principal.WindowsPrincipal(
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-MainClean {
    $requiredBranch = if ($AllowNonMainValidation) { "" } else { "main" }
    Get-ReleaseGitIdentity `
        -RepositoryRoot $repoRoot `
        -RequiredBranch $requiredBranch | Out-Null
}

function Run-Checked {
    param([string]$Name, [scriptblock]$Action)
    Write-Host "`n=== $Name ==="
    & $Action
    $phaseExitCode = $LASTEXITCODE
    if ($null -ne $phaseExitCode -and $phaseExitCode -ne 0) {
        throw "$Name failed with exit code $phaseExitCode."
    }
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
        Run-Checked -Name "FINALIZE RELEASE" -Action {
            & $inboxWindowsPowerShell @args
        }
        Write-Host "admin-finalize complete. Next run gpu-validate in NON-admin desktop session."
    }

    "gpu-validate" {
        if (Test-IsAdmin) {
            throw "gpu-validate must run in NON-admin desktop PowerShell."
        }
        Assert-MainClean
        Run-Checked -Name "GPU FROZEN VALIDATION" -Action {
            & $inboxWindowsPowerShell `
                -NoProfile `
                -ExecutionPolicy Bypass `
                -File scripts/validate_frozen_runtime.ps1 `
                -Variant GPU
        }
        Write-Host "gpu-validate complete. Next run admin-compat in Administrator PowerShell."
    }

    "admin-compat" {
        if (-not (Test-IsAdmin)) {
            throw "admin-compat must run in Administrator PowerShell."
        }
        Assert-MainClean
        Run-Checked -Name "COMPAT FROZEN VALIDATION" -Action {
            & $inboxWindowsPowerShell `
                -NoProfile `
                -ExecutionPolicy Bypass `
                -File scripts/validate_frozen_runtime.ps1 `
                -Variant Compat
        }
        if ([string]::IsNullOrWhiteSpace($Operator)) {
            throw "Provide -Operator for manual validation recording (e.g. -Operator GrihmLord)."
        }
        Run-Checked -Name "RECORD MANUAL RELEASE VALIDATION" -Action {
            $manualArgs = @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                "scripts/record_manual_release_validation.ps1",
                "-Version", $Version,
                "-Operator", $Operator
            )
            if ($AllowUnsigned) { $manualArgs += "-AllowUnsigned" }
            & $inboxWindowsPowerShell @manualArgs
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
            $stageArgs = @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                "scripts/stage_release.ps1", "-Mode", "Draft",
                "-Version", $Version
            )
            if ($AllowUnsigned) { $stageArgs += "-AllowUnsigned" }
            & $inboxWindowsPowerShell @stageArgs
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
            $stageArgs = @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                "scripts/stage_release.ps1", "-Mode", "Publish",
                "-Version", $Version
            )
            if ($AllowUnsigned) { $stageArgs += "-AllowUnsigned" }
            & $inboxWindowsPowerShell @stageArgs
        }
        Write-Host "admin-stage-publish complete. All blocked release gates finished."
    }
}
