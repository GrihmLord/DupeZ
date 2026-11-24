#requires -Version 5.1
<#
.SYNOPSIS
Safe front door for the DupeZ release gate launcher.

.DESCRIPTION
Delegates to release_gate_launcher.ps1 so every release uses the same
exact-commit finalization, frozen-runtime, hardware, manual, draft-verification,
and publication sequence. The default action is read-only status; advancing a
release requires an explicit -Phase auto or named phase. Auto mode stops before
publication, which always requires the explicit admin-stage-publish phase.
#>

[CmdletBinding()]
param(
    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.8.0",

    [ValidateSet(
        "status",
        "auto",
        "reset",
        "admin-finalize",
        "gpu-validate",
        "admin-compat",
        "admin-stage-draft",
        "admin-stage-publish"
    )]
    [string]$Phase = "status",

    [ValidateLength(0, 80)]
    [ValidatePattern('^$|^[\p{L}\p{M}\p{N}][\p{L}\p{M}\p{N} ._-]{0,79}$')]
    [string]$Operator = "",

    [switch]$AllowUnsigned,

    [switch]$AllowNonMainValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$launcherPath = Join-Path $PSScriptRoot "release_gate_launcher.ps1"
if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Canonical release gate launcher is missing: $launcherPath"
}

$launcherArguments = @{
    Phase = $Phase
    Version = $Version
}
if (-not [string]::IsNullOrWhiteSpace($Operator)) {
    $launcherArguments.Operator = $Operator
}
if ($AllowUnsigned) {
    $launcherArguments.AllowUnsigned = $true
}
if ($AllowNonMainValidation) {
    $launcherArguments.AllowNonMainValidation = $true
}

& $launcherPath @launcherArguments
