#requires -Version 5.1
<#
Interactive/auto launcher for blocked release gates.

Purpose:
- Walk the blocked release gates in strict order.
- Persist progress to dist/blocked-release-gates-progress.json.
- Auto-elevate admin-required phases.
- Prompt for non-admin context where required (GPU validation).
#>

[CmdletBinding()]
param(
    [ValidateSet("auto", "admin-finalize", "gpu-validate", "admin-compat", "admin-stage-draft", "admin-stage-publish", "status", "reset")]
    [string]$Phase = "auto",

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.7.9",

    [string]$Operator = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$statePath = Join-Path $repoRoot "dist\blocked-release-gates-progress.json"
$sequence = @(
    "admin-finalize",
    "gpu-validate",
    "admin-compat",
    "admin-stage-draft",
    "admin-stage-publish"
)

$phaseMeta = @{
    "admin-finalize" = @{ requiresAdmin = $true;  note = "Finalize + dist/signing gates" }
    "gpu-validate" = @{ requiresAdmin = $false; note = "GPU frozen runtime validation (must be non-admin)" }
    "admin-compat" = @{ requiresAdmin = $true;  note = "Compat validation + manual validation record" }
    "admin-stage-draft" = @{ requiresAdmin = $true;  note = "Stage draft release" }
    "admin-stage-publish" = @{ requiresAdmin = $true;  note = "Publish staged release" }
}

function Test-IsAdmin {
    return (
        New-Object Security.Principal.WindowsPrincipal(
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-DefaultState {
    return [ordered]@{
        schema = "dupez.blocked-release-gates-progress.v1"
        version = $Version
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        phases = [ordered]@{}
    }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return New-DefaultState
    }
    try {
        $raw = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $h = [ordered]@{
            schema = [string]$raw.schema
            version = [string]$raw.version
            updated_at_utc = [string]$raw.updated_at_utc
            phases = [ordered]@{}
        }
        foreach ($name in $sequence) {
            $prop = $null
            if ($null -ne $raw.phases) {
                $prop = $raw.phases.PSObject.Properties[$name]
            }
            if ($null -ne $prop -and $null -ne $prop.Value) {
                $h.phases[$name] = [string]$prop.Value
            }
        }
        return $h
    }
    catch {
        Write-Warning "Could not parse $statePath. Reinitializing progress state."
        $default = New-DefaultState
        Write-State -state $default
        return $default
    }
}

function Write-State([hashtable]$state) {
    $state.updated_at_utc = [DateTime]::UtcNow.ToString("o")
    $json = $state | ConvertTo-Json -Depth 6
    $dir = Split-Path -Parent $statePath
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    Set-Content -LiteralPath $statePath -Value $json -Encoding UTF8
}

function Show-Status([hashtable]$state) {
    Write-Host "\nBlocked release gates status (v$Version):"
    foreach ($name in $sequence) {
        $status = if ($state.phases.Contains($name)) { $state.phases[$name] } else { "PENDING" }
        Write-Host ("- {0}: {1}" -f $name, $status)
    }
    Write-Host "State file: $statePath"
}

function Next-Phase([hashtable]$state) {
    foreach ($name in $sequence) {
        $status = if ($state.phases.Contains($name)) { $state.phases[$name] } else { "PENDING" }
        if ($status -ne "DONE") {
            return $name
        }
    }
    return $null
}

function Require-OperatorForPhase([string]$phaseName) {
    if ($phaseName -eq "admin-compat" -and [string]::IsNullOrWhiteSpace($Operator)) {
        throw "admin-compat requires -Operator <name> for manual validation record."
    }
}

function Invoke-Phase([string]$phaseName, [hashtable]$state) {
    if (-not $phaseMeta.ContainsKey($phaseName)) {
        throw "Unknown phase: $phaseName"
    }

    Require-OperatorForPhase -phaseName $phaseName

    $isAdmin = Test-IsAdmin
    $needsAdmin = [bool]$phaseMeta[$phaseName].requiresAdmin

    if ($needsAdmin -and -not $isAdmin) {
        Write-Host "\nPhase '$phaseName' requires Administrator PowerShell. Relaunching elevated..."
        $argList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", ('"' + $PSCommandPath + '"'),
            "-Phase", $phaseName,
            "-Version", $Version
        )
        if (-not [string]::IsNullOrWhiteSpace($Operator)) {
            $argList += @("-Operator", ('"' + $Operator + '"'))
        }
        Start-Process -FilePath "powershell" -Verb RunAs -ArgumentList ($argList -join " ")
        return "RELAUNCHED_ELEVATED"
    }

    if (-not $needsAdmin -and $isAdmin) {
        throw "Phase '$phaseName' must run in a NON-admin desktop PowerShell session. Open a standard shell and rerun."
    }

    Write-Host "\n=== Running $phaseName ==="
    Write-Host "Context note: $($phaseMeta[$phaseName].note)"

    $seqArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "scripts/blocked_release_gates_sequence.ps1",
        "-Phase", $phaseName,
        "-Version", $Version
    )
    if (-not [string]::IsNullOrWhiteSpace($Operator)) {
        $seqArgs += @("-Operator", $Operator)
    }

    & powershell @seqArgs
    if ($LASTEXITCODE -ne 0) {
        $state.phases[$phaseName] = "FAILED"
        Write-State -state $state
        throw "Phase '$phaseName' failed with exit code $LASTEXITCODE."
    }

    $state.phases[$phaseName] = "DONE"
    Write-State -state $state
    return "DONE"
}

if ($Phase -eq "reset") {
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Remove-Item -LiteralPath $statePath -Force
        Write-Host "Reset progress state: $statePath"
    }
    else {
        Write-Host "No state file to reset."
    }
    exit 0
}

$state = Read-State

if ($Phase -eq "status") {
    Show-Status -state $state
    exit 0
}

$selected = $Phase
if ($Phase -eq "auto") {
    $selected = Next-Phase -state $state
    if ($null -eq $selected) {
        Show-Status -state $state
        Write-Host "\nAll blocked release gates are complete."
        exit 0
    }
}

$result = Invoke-Phase -phaseName $selected -state $state
if ($result -eq "RELAUNCHED_ELEVATED") {
    Write-Host "Elevated window launched for '$selected'. After it completes, rerun this launcher."
    exit 0
}

$state = Read-State
Show-Status -state $state
$next = Next-Phase -state $state
if ($null -ne $next) {
    Write-Host "\nNext phase: $next"
    if ($next -eq "gpu-validate") {
        Write-Host "Run next from NON-admin desktop PowerShell."
    }
    elseif ([bool]$phaseMeta[$next].requiresAdmin) {
        Write-Host "Run next from ADMIN PowerShell (or use -Phase auto and allow elevation)."
    }
}
else {
    Write-Host "\nAll blocked release gates complete."
}
