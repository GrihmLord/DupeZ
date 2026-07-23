#requires -Version 5.1
<#
Stage or publish an already-finalized and manually validated DupeZ release.

Raw host evidence remains private in dist/. This script validates it against the
current commit and executable hashes, emits a sanitized public attestation, and
refuses to replace assets on an already-published release.
#>

[CmdletBinding()]
param(
    [ValidateSet("Draft", "Publish")]
    [string]$Mode = "Draft",

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.7.9",

    [string]$Repository = "GrihmLord/DupeZ"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot
$distRoot = Join-Path $repoRoot "dist"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $false)]
        [string[]]$ArgumentList = @(),

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Host "`n=== $Description ==="
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description is missing: $Path"
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        throw "$Description is not valid JSON: $Path"
    }
}

function Get-Sha256 {
    param([string]$Path)
    return (
        Get-FileHash -LiteralPath $Path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}

function Assert-FrozenEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Evidence,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedVariant,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedHash,

        [Parameter(Mandatory = $true)]
        [string]$Commit
    )

    if ($Evidence.schema -ne "dupez.frozen-runtime-validation.v1") {
        throw "$ExpectedVariant frozen evidence schema mismatch."
    }
    if ($Evidence.variant -ne $ExpectedVariant) {
        throw "$ExpectedVariant frozen evidence variant mismatch."
    }
    if ($Evidence.commit -ne $Commit) {
        throw "$ExpectedVariant frozen evidence commit mismatch."
    }
    if ($Evidence.executable_sha256 -ne $ExpectedHash) {
        throw "$ExpectedVariant frozen evidence hash mismatch."
    }

    $runs = @($Evidence.runs)
    if ($runs.Count -lt 2) {
        throw "$ExpectedVariant frozen evidence must include both resource profiles."
    }
    $profiles = @($runs | ForEach-Object { $_.profile } | Sort-Object -Unique)
    foreach ($required in @("normal", "forced-low-resource")) {
        if ($required -notin $profiles) {
            throw "$ExpectedVariant frozen evidence lacks $required."
        }
    }
    foreach ($run in $runs) {
        if (-not $run.clean_exit -or [int]$run.exit_code -ne 0) {
            throw "$ExpectedVariant frozen evidence includes a failed lifecycle."
        }
        if (-not $run.map_result) {
            throw "$ExpectedVariant frozen evidence includes a run without a map result."
        }
    }

    if ($ExpectedVariant -eq "GPU") {
        if ($Evidence.validation_host.administrator) {
            throw "GPU frozen validation was performed from an elevated session."
        }
        foreach ($run in $runs) {
            if ($run.architecture_expectation -ne "split-medium-integrity-gui") {
                throw "GPU frozen evidence architecture mismatch."
            }
        }
    }
    else {
        if (-not $Evidence.validation_host.administrator) {
            throw "Compat frozen validation was not performed as Administrator."
        }
        foreach ($run in $runs) {
            if ($run.architecture_expectation -ne "inproc-high-integrity") {
                throw "Compat frozen evidence architecture mismatch."
            }
        }
    }
}

$git = (Get-Command git -ErrorAction Stop).Source
$gh = (Get-Command gh -ErrorAction Stop).Source
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Repository Python was not found at .venv\Scripts\python.exe."
}

$branch = (& $git branch --show-current).Trim()
if ($branch -ne "main") {
    throw "Release staging must run from main; current branch is $branch."
}
if (@(& $git status --porcelain).Count -ne 0) {
    & $git status --short
    throw "Repository must be clean before release staging."
}
$commit = (& $git rev-parse HEAD).Trim()
if (-not $commit) {
    throw "Could not resolve the release commit."
}
if (
    [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and
    [string]::IsNullOrWhiteSpace($env:GH_TOKEN)
) {
    throw "GITHUB_TOKEN or GH_TOKEN is required."
}

Invoke-Checked -FilePath $pythonPath -Description "FINAL DIST RELEASE PREFLIGHT" -ArgumentList @(
    "-I", "scripts\release_preflight.py",
    "--version", $Version,
    "--dist"
)

$gpuPath = Join-Path $distRoot "DupeZ-GPU.exe"
$compatPath = Join-Path $distRoot "DupeZ-Compat.exe"
$installerPath = Join-Path $distRoot "DupeZ_v${Version}_Setup.exe"
$gpuHash = Get-Sha256 -Path $gpuPath
$compatHash = Get-Sha256 -Path $compatPath
$installerHash = Get-Sha256 -Path $installerPath

$gpuEvidence = Read-JsonFile `
    -Path (Join-Path $distRoot "frozen-runtime-evidence-gpu.json") `
    -Description "GPU frozen runtime evidence"
$compatEvidence = Read-JsonFile `
    -Path (Join-Path $distRoot "frozen-runtime-evidence-compat.json") `
    -Description "Compat frozen runtime evidence"
$manualEvidence = Read-JsonFile `
    -Path (Join-Path $distRoot "manual-release-validation.json") `
    -Description "manual release validation"

Assert-FrozenEvidence `
    -Evidence $gpuEvidence `
    -ExpectedVariant "GPU" `
    -ExpectedHash $gpuHash `
    -Commit $commit
Assert-FrozenEvidence `
    -Evidence $compatEvidence `
    -ExpectedVariant "Compat" `
    -ExpectedHash $compatHash `
    -Commit $commit

if ($manualEvidence.schema -ne "dupez.manual-release-validation.v1") {
    throw "Manual release validation schema mismatch."
}
if ($manualEvidence.version -ne $Version -or $manualEvidence.commit -ne $commit) {
    throw "Manual release validation version/commit mismatch."
}
if (
    $manualEvidence.artifacts.gpu_sha256 -ne $gpuHash -or
    $manualEvidence.artifacts.compat_sha256 -ne $compatHash -or
    $manualEvidence.artifacts.installer_sha256 -ne $installerHash
) {
    throw "Manual release validation artifact hash mismatch."
}
$manualGates = @($manualEvidence.gates.PSObject.Properties)
if ($manualGates.Count -lt 16) {
    throw "Manual release validation is incomplete."
}
foreach ($gate in $manualGates) {
    if ($gate.Value -ne $true) {
        throw "Manual release gate not completed: $($gate.Name)"
    }
}

$publicValidation = [ordered]@{
    schema = "dupez.release-validation-attestation.v1"
    version = $Version
    commit = $commit
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    artifacts = [ordered]@{
        gpu_sha256 = $gpuHash
        compat_sha256 = $compatHash
        installer_sha256 = $installerHash
    }
    frozen_runtime = [ordered]@{
        gpu = [ordered]@{
            profiles = @($gpuEvidence.runs | ForEach-Object { $_.profile } | Sort-Object -Unique)
            runs = @($gpuEvidence.runs).Count
            map_results = @($gpuEvidence.runs | ForEach-Object { $_.map_result } | Sort-Object -Unique)
            clean_exit = $true
            gui_integrity = "medium"
        }
        compat = [ordered]@{
            profiles = @($compatEvidence.runs | ForEach-Object { $_.profile } | Sort-Object -Unique)
            runs = @($compatEvidence.runs).Count
            map_results = @($compatEvidence.runs | ForEach-Object { $_.map_result } | Sort-Object -Unique)
            clean_exit = $true
            gui_integrity = "high"
        }
    }
    manual_validation = [ordered]@{
        recorded_at_utc = $manualEvidence.recorded_at_utc
        completed_gates = @($manualGates | ForEach-Object { $_.Name } | Sort-Object)
    }
}
$publicValidationPath = Join-Path $distRoot "release-validation-attestation.json"
$publicValidation | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $publicValidationPath -Encoding UTF8

$assetNames = @(
    "DupeZ-GPU.exe",
    "DupeZ-Compat.exe",
    "DupeZ_v${Version}_Setup.exe",
    "DupeZ_Setup.exe",
    "DupeZ_Setup.exe.manifest.json",
    "DupeZ_Setup.exe.manifest.sig",
    "DupeZ.sbom.json",
    "DupeZ.vex.json",
    "binary-provenance.json",
    "SHA256SUMS.txt",
    "release-attestation.json",
    "release-validation-attestation.json",
    "DefenderScan.txt"
)
$assets = @(
    foreach ($name in $assetNames) {
        $path = Join-Path $distRoot $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required staged asset missing: dist\$name"
        }
        $item = Get-Item -LiteralPath $path
        if ($item.Length -le 0) {
            throw "Required staged asset is empty: dist\$name"
        }
        $item
    }
)

# Verify the finalizer's primary hashes before adding the sanitized validation
# attestation hash. Raw host/manual evidence remains private and is not uploaded.
$sumPath = Join-Path $distRoot "SHA256SUMS.txt"
$sumLines = @(Get-Content -LiteralPath $sumPath)
$covered = @{}
foreach ($line in $sumLines) {
    if ($line -match '^([0-9a-fA-F]{64})\s{2}(.+)$') {
        $covered[$Matches[2]] = $Matches[1].ToLowerInvariant()
    }
}
foreach ($asset in $assets) {
    if ($asset.Name -in @(
        "SHA256SUMS.txt",
        "release-attestation.json",
        "release-validation-attestation.json",
        "DefenderScan.txt"
    )) {
        continue
    }
    if (-not $covered.ContainsKey($asset.Name)) {
        throw "SHA256SUMS.txt does not cover $($asset.Name)."
    }
    $actual = Get-Sha256 -Path $asset.FullName
    if ($actual -ne $covered[$asset.Name]) {
        throw "SHA256SUMS.txt mismatch for $($asset.Name)."
    }
}
$validationHash = Get-Sha256 -Path $publicValidationPath
$sumLines = @(
    $sumLines | Where-Object {
        $_ -notmatch '\s{2}release-validation-attestation\.json$'
    }
)
$sumLines += "$validationHash  release-validation-attestation.json"
Set-Content -LiteralPath $sumPath -Encoding ASCII -Value $sumLines

$tag = "v$Version"
$notes = Join-Path $repoRoot "docs\release-notes\v$Version.md"
if (-not (Test-Path -LiteralPath $notes -PathType Leaf)) {
    throw "Release notes missing: docs\release-notes\v$Version.md"
}

$releaseJson = & $gh release view $tag --repo $Repository --json isDraft,tagName,targetCommitish 2>$null
$releaseExists = $LASTEXITCODE -eq 0
if ($releaseExists) {
    $release = $releaseJson | ConvertFrom-Json
    if (-not $release.isDraft) {
        throw "Release $tag is already published; immutable assets will not be replaced."
    }
}
else {
    Invoke-Checked -FilePath $gh -Description "CREATE DRAFT RELEASE" -ArgumentList @(
        "release", "create", $tag,
        "--repo", $Repository,
        "--draft",
        "--target", $commit,
        "--title", "DupeZ v$Version",
        "--notes-file", $notes
    )
}

$uploadArguments = @("release", "upload", $tag, "--repo", $Repository, "--clobber")
$uploadArguments += @($assets | ForEach-Object { $_.FullName })
Invoke-Checked -FilePath $gh -Description "UPLOAD VERIFIED RELEASE ASSETS" -ArgumentList $uploadArguments

if ($Mode -eq "Publish") {
    Invoke-Checked -FilePath $gh -Description "PUBLISH VERIFIED RELEASE" -ArgumentList @(
        "release", "edit", $tag,
        "--repo", $Repository,
        "--draft=false",
        "--latest"
    )
}

Write-Host "`nRELEASE STAGING: PASS" -ForegroundColor Green
Write-Host "Tag: $tag"
Write-Host "Commit: $commit"
Write-Host "Mode: $Mode"
Write-Host "Assets: $($assets.Count)"
