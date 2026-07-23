#requires -Version 5.1
<#
Stage or publish an already-finalized DupeZ release.

This script does not build or sign anything. It re-runs the fail-closed dist
preflight, requires the complete evidence set, and refuses to replace assets on
an already-published release.
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
if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and [string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
    throw "GITHUB_TOKEN or GH_TOKEN is required."
}

Invoke-Checked -FilePath $pythonPath -Description "FINAL DIST RELEASE PREFLIGHT" -ArgumentList @(
    "-I", "scripts\release_preflight.py",
    "--version", $Version,
    "--dist"
)

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
    "DefenderScan.txt"
)
$assets = @(
    foreach ($name in $assetNames) {
        $path = Join-Path $repoRoot "dist\$name"
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

# Verify SHA256SUMS covers every primary release artifact before upload.
$sumLines = Get-Content -LiteralPath (Join-Path $repoRoot "dist\SHA256SUMS.txt")
$covered = @{}
foreach ($line in $sumLines) {
    if ($line -match '^([0-9a-fA-F]{64})\s{2}(.+)$') {
        $covered[$Matches[2]] = $Matches[1].ToLowerInvariant()
    }
}
foreach ($asset in $assets) {
    if ($asset.Name -in @("SHA256SUMS.txt", "release-attestation.json", "DefenderScan.txt")) {
        continue
    }
    if (-not $covered.ContainsKey($asset.Name)) {
        throw "SHA256SUMS.txt does not cover $($asset.Name)."
    }
    $actual = (Get-FileHash -LiteralPath $asset.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $covered[$asset.Name]) {
        throw "SHA256SUMS.txt mismatch for $($asset.Name)."
    }
}

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
