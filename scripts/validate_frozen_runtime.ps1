#requires -Version 5.1
<#
Run the architecture-correct frozen lifecycle validator.

GPU must run from a standard desktop PowerShell session. Compat must run from
Administrator PowerShell. The Python implementation follows PyInstaller's
one-file process tree, exercises the real dashboard shortcuts, verifies map
startup and clean shutdown, and writes private hash-bound evidence to dist/.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("GPU", "Compat")]
    [string]$Variant,

    [string]$DistDirectory = "dist",

    [ValidateRange(1, 5)]
    [int]$CyclesPerProfile = 1,

    [ValidateRange(30, 300)]
    [int]$StartupTimeoutSeconds = 150,

    [ValidateRange(15, 180)]
    [int]$MapTimeoutSeconds = 60,

    [ValidateRange(10, 120)]
    [int]$ShutdownTimeoutSeconds = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$isAdmin = (
    New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($Variant -eq "GPU" -and $isAdmin) {
    throw (
        "GPU validation must run from a standard, non-Administrator desktop " +
        "PowerShell session so the split GUI remains Medium Integrity."
    )
}
if ($Variant -eq "Compat" -and -not $isAdmin) {
    throw "Compat validation must run from Administrator PowerShell."
}

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repository Python was not found at .venv\Scripts\python.exe."
}

& $python `
    -I `
    "scripts\validate_frozen_runtime.py" `
    --variant $Variant `
    --dist-directory $DistDirectory `
    --cycles-per-profile $CyclesPerProfile `
    --startup-timeout $StartupTimeoutSeconds `
    --map-timeout $MapTimeoutSeconds `
    --shutdown-timeout $ShutdownTimeoutSeconds

if ($LASTEXITCODE -ne 0) {
    throw "Frozen $Variant runtime validation failed with exit code $LASTEXITCODE."
}
