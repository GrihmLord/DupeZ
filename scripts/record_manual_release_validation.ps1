#requires -Version 5.1
<#
Record the human-observed v5.7.9 release gates against the exact frozen and
installer artifacts already present in dist/. This script is intentionally
interactive: every gate requires an explicit YES response from the operator.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Operator,

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.7.9"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot
$distRoot = Join-Path $repoRoot "dist"
if (-not (Test-Path -LiteralPath $distRoot -PathType Container)) {
    throw "dist/ does not exist. Build and validate the release first."
}

$git = (Get-Command git -ErrorAction Stop).Source
$commit = (& $git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) {
    throw "Could not resolve the current commit."
}
if ((& $git branch --show-current).Trim() -ne "main") {
    throw "Manual release validation must be recorded from main."
}
if (@(& $git status --porcelain).Count -ne 0) {
    & $git status --short
    throw "Repository must be clean."
}

$gpuPath = Join-Path $distRoot "DupeZ-GPU.exe"
$compatPath = Join-Path $distRoot "DupeZ-Compat.exe"
$installerPath = Join-Path $distRoot "DupeZ_v${Version}_Setup.exe"
foreach ($path in @($gpuPath, $compatPath, $installerPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required exact artifact missing: $path"
    }
}

$gpuHash = (Get-FileHash -LiteralPath $gpuPath -Algorithm SHA256).Hash.ToLowerInvariant()
$compatHash = (Get-FileHash -LiteralPath $compatPath -Algorithm SHA256).Hash.ToLowerInvariant()
$installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()

function Read-Evidence {
    param(
        [string]$Path,
        [string]$ExpectedVariant,
        [string]$ExpectedHash
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Frozen runtime evidence missing: $Path"
    }
    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($payload.schema -ne "dupez.frozen-runtime-validation.v1") {
        throw "Unexpected frozen evidence schema in $Path."
    }
    if ($payload.variant -ne $ExpectedVariant) {
        throw "Frozen evidence variant mismatch in $Path."
    }
    if ($payload.commit -ne $commit) {
        throw "Frozen evidence commit mismatch in $Path."
    }
    if ($payload.executable_sha256 -ne $ExpectedHash) {
        throw "Frozen evidence executable hash mismatch in $Path."
    }
    $profiles = @($payload.runs | ForEach-Object { $_.profile } | Sort-Object -Unique)
    foreach ($requiredProfile in @("normal", "forced-low-resource")) {
        if ($requiredProfile -notin $profiles) {
            throw "$ExpectedVariant evidence does not contain $requiredProfile."
        }
    }
    foreach ($run in @($payload.runs)) {
        if (-not $run.clean_exit -or [int]$run.exit_code -ne 0) {
            throw "$ExpectedVariant frozen evidence contains a failed run."
        }
        if (-not $run.map_result) {
            throw "$ExpectedVariant frozen evidence lacks a map result."
        }
    }
    return $payload
}

$gpuEvidencePath = Join-Path $distRoot "frozen-runtime-evidence-gpu.json"
$compatEvidencePath = Join-Path $distRoot "frozen-runtime-evidence-compat.json"
$gpuEvidence = Read-Evidence -Path $gpuEvidencePath -ExpectedVariant "GPU" -ExpectedHash $gpuHash
$compatEvidence = Read-Evidence -Path $compatEvidencePath -ExpectedVariant "Compat" -ExpectedHash $compatHash

$gatePrompts = [ordered]@{
    hidden_clumsy_no_flash = "Normal DupeZ disruption kept native Clumsy hidden with no visible startup flash"
    gpu_diagnostic_restore = "GPU frozen build restored and re-hid the owned Clumsy diagnostic window"
    compat_diagnostic_restore = "Compat frozen build restored and re-hid the owned Clumsy diagnostic window"
    map_failure_retry = "Embedded map failure state displayed Retry and a retry succeeded without restarting"
    network_scan = "Network scan found only expected local devices and remained responsive"
    manual_disruption = "Manual disruption started, reported the selected engine/layer, and stopped cleanly"
    event_queue_stop = "Ordered event queue started and Stop prevented later events from continuing"
    hotkey = "Configured hotkeys worked and the panic/stop action restored network state"
    tray = "Tray minimize, restore, status, Stop All, and Quit worked"
    obs_overlay = "OBS overlay server started, served its page, and stopped cleanly"
    account_tracker = "Account tracker loaded, switched, persisted, and cleared the active account"
    smart_ops = "Smart Ops offline/provider path remained responsive and routed through selected engine/layer"
    diagnostics_support_bundle = "Diagnostics, network health, and support/backup bundle completed without secrets"
    installer_fresh_install = "Signed installer completed a fresh installation and launched the stable dupez.exe"
    installer_upgrade = "Signed installer upgraded the previous installed version without stale processes or data loss"
    installer_uninstall = "Uninstall removed installed binaries/shortcuts while preserving intended per-user data"
}

$completed = [ordered]@{}
Write-Host "`nDupeZ v$Version manual validation — exact commit $commit"
Write-Host "GPU SHA256:       $gpuHash"
Write-Host "Compat SHA256:    $compatHash"
Write-Host "Installer SHA256: $installerHash"
Write-Host "`nType YES for each gate only after observing it on these exact artifacts."

foreach ($entry in $gatePrompts.GetEnumerator()) {
    $answer = Read-Host "[$($entry.Key)] $($entry.Value) (YES/no)"
    if ($answer.Trim().ToUpperInvariant() -ne "YES") {
        throw "Manual release validation stopped at gate: $($entry.Key)"
    }
    $completed[$entry.Key] = $true
}

$notes = Read-Host "Optional private validation notes (press Enter for none)"
$payload = [ordered]@{
    schema = "dupez.manual-release-validation.v1"
    version = $Version
    commit = $commit
    recorded_at_utc = [DateTime]::UtcNow.ToString("o")
    operator = $Operator
    artifacts = [ordered]@{
        gpu_sha256 = $gpuHash
        compat_sha256 = $compatHash
        installer_sha256 = $installerHash
    }
    frozen_evidence = [ordered]@{
        gpu_schema = $gpuEvidence.schema
        gpu_runs = @($gpuEvidence.runs).Count
        compat_schema = $compatEvidence.schema
        compat_runs = @($compatEvidence.runs).Count
    }
    gates = $completed
    notes = $notes
}
$outputPath = Join-Path $distRoot "manual-release-validation.json"
$payload | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $outputPath -Encoding UTF8

Write-Host "`nMANUAL RELEASE VALIDATION RECORDED" -ForegroundColor Green
Write-Host "Evidence: $outputPath"
