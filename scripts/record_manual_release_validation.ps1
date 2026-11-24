#requires -Version 5.1
<#
Record the human-observed v5.8.0 release gates against the exact frozen and
installer artifacts already present in dist/. This script is intentionally
interactive: every gate requires an explicit YES response from the operator.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Operator,

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.8.0",

    [switch]$AllowUnsigned
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "frozen_runtime_evidence_contract.ps1")
. (Join-Path $PSScriptRoot "release_git_contract.ps1")

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot
$distRoot = Join-Path $repoRoot "dist"
if (-not (Test-Path -LiteralPath $distRoot -PathType Container)) {
    throw "dist/ does not exist. Build and validate the release first."
}
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Repository Python was not found at .venv\Scripts\python.exe."
}

$sourceIdentity = Get-ReleaseGitIdentity `
    -RepositoryRoot $repoRoot `
    -RequiredBranch "main"
$commit = $sourceIdentity.Commit

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

$attestationPath = Join-Path $distRoot "release-attestation.json"
if (-not (Test-Path -LiteralPath $attestationPath -PathType Leaf)) {
    throw "Release attestation missing: $attestationPath"
}
$attestation = Get-Content -LiteralPath $attestationPath -Raw | ConvertFrom-Json
if ($attestation.schema -ne "dupez.release-attestation.v1") {
    throw "Unexpected release attestation schema."
}
if ($attestation.version -ne $Version -or $attestation.commit -ne $commit) {
    throw "Release attestation version/commit does not match the manual validation target."
}

$expectedSigningMode = if ($AllowUnsigned) { "unsigned" } else { "authenticode" }
if ($attestation.distribution_signing_mode -ne $expectedSigningMode) {
    throw (
        "Release attestation signing mode mismatch: expected $expectedSigningMode, " +
        "found $($attestation.distribution_signing_mode)."
    )
}

$expectedArtifactHashes = [ordered]@{
    "DupeZ-GPU.exe" = $gpuHash
    "DupeZ-Compat.exe" = $compatHash
    "DupeZ_v${Version}_Setup.exe" = $installerHash
}
foreach ($entry in $expectedArtifactHashes.GetEnumerator()) {
    $artifact = @($attestation.artifacts | Where-Object { $_.name -eq $entry.Key })
    if ($artifact.Count -ne 1 -or $artifact[0].sha256 -ne $entry.Value) {
        throw "Release attestation hash mismatch for $($entry.Key)."
    }
    $signature = @($attestation.authenticode | Where-Object { $_.name -eq $entry.Key })
    if ($signature.Count -ne 1) {
        throw "Release attestation Authenticode record missing for $($entry.Key)."
    }
    $expectedStatus = if ($AllowUnsigned) { "Unsigned" } else { "Valid" }
    if ($signature[0].status -ne $expectedStatus) {
        throw (
            "Release attestation Authenticode status mismatch for $($entry.Key): " +
            "expected $expectedStatus, found $($signature[0].status)."
        )
    }
}

function Read-Evidence {
    param(
        [string]$Path,
        [string]$ExpectedVariant,
        [string]$ExpectedExecutable,
        [string]$ExpectedHash
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Frozen runtime evidence missing: $Path"
    }
    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    Assert-FrozenRuntimeEvidenceContract `
        -Evidence $payload `
        -ExpectedVariant $ExpectedVariant `
        -ExpectedExecutable $ExpectedExecutable `
        -ExpectedHash $ExpectedHash `
        -ExpectedCommit $commit
    return $payload
}

$gpuEvidencePath = Join-Path $distRoot "frozen-runtime-evidence-gpu.json"
$compatEvidencePath = Join-Path $distRoot "frozen-runtime-evidence-compat.json"
$gpuEvidence = Read-Evidence `
    -Path $gpuEvidencePath `
    -ExpectedVariant "GPU" `
    -ExpectedExecutable "DupeZ-GPU.exe" `
    -ExpectedHash $gpuHash
$compatEvidence = Read-Evidence `
    -Path $compatEvidencePath `
    -ExpectedVariant "Compat" `
    -ExpectedExecutable "DupeZ-Compat.exe" `
    -ExpectedHash $compatHash
$hardwareEvidencePath = Join-Path $distRoot "hardware-smoketest-evidence.json"
if (-not (Test-Path -LiteralPath $hardwareEvidencePath -PathType Leaf)) {
    throw "Hardware-smoketest evidence missing: $hardwareEvidencePath"
}
& $pythonPath `
    -I scripts\hardware_evidence.py validate `
    --evidence $hardwareEvidencePath `
    --commit $commit
if ($LASTEXITCODE -ne 0) {
    throw "Hardware-smoketest evidence does not match this commit/provenance."
}
$hardwareEvidence = Get-Content -LiteralPath $hardwareEvidencePath -Raw |
    ConvertFrom-Json

$installerTrustDescription = if ($AllowUnsigned) {
    "Authorized unsigned release installer (with public disclosure)"
}
else {
    "Authenticode-signed release installer"
}

$gateDescriptions = [ordered]@{
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
    installer_fresh_install = "$installerTrustDescription completed a fresh installation and launched the stable dupez.exe"
    installer_upgrade = "$installerTrustDescription upgraded the previous installed version without stale processes or data loss"
    installer_uninstall = "Uninstall removed installed binaries/shortcuts while preserving intended per-user data"
}

$completed = [ordered]@{}
Write-Host "`nDupeZ v$Version manual validation - exact commit $commit"
Write-Host "GPU SHA256:       $gpuHash"
Write-Host "Compat SHA256:    $compatHash"
Write-Host "Installer SHA256: $installerHash"
Write-Host "`nType YES for each gate only after observing it on these exact artifacts."

foreach ($entry in $gateDescriptions.GetEnumerator()) {
    $answer = Read-Host "[$($entry.Key)] $($entry.Value) (YES/no)"
    if ($answer.Trim().ToUpperInvariant() -ne "YES") {
        throw "Manual release validation stopped at gate: $($entry.Key)"
    }
    $completed[$entry.Key] = $true
}

$notes = Read-Host "Optional private validation notes (press Enter for none)"
Assert-ReleaseGitIdentityUnchanged `
    -RepositoryRoot $repoRoot `
    -ExpectedCommit $commit `
    -RequiredBranch "main" | Out-Null
$payload = [ordered]@{
    schema = "dupez.manual-release-validation.v1"
    version = $Version
    commit = $commit
    recorded_at_utc = [DateTime]::UtcNow.ToString("o")
    operator = $Operator
    distribution_signing_mode = $expectedSigningMode
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
    hardware_evidence = [ordered]@{
        schema = $hardwareEvidence.schema
        commit = $hardwareEvidence.commit
        test_count = [int]$hardwareEvidence.tests.count
        source_native_artifacts = @($hardwareEvidence.source_native_artifacts)
    }
    gates = $completed
    notes = $notes
}
$outputPath = Join-Path $distRoot "manual-release-validation.json"
$payload | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $outputPath -Encoding UTF8

Write-Host "`nMANUAL RELEASE VALIDATION RECORDED" -ForegroundColor Green
Write-Host "Evidence: $outputPath"
