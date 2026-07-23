#requires -Version 5.1
<#[
.SYNOPSIS
Build, sign, scan, attest, and optionally stage a DupeZ GitHub release.

.DESCRIPTION
This script is intended for the protected Windows release-signing host. It
never generates or exports signing keys. The existing Authenticode PFX and the
Ed25519 private key matching the public key pinned in app/core/update_verify.py
must already exist outside the repository.

Modes:
  Validate  Build and run every local release gate; do not touch GitHub.
  Draft     Create/update a GitHub draft release after all gates pass.
  Publish   Publish an already-complete draft after re-running all gates.

Examples:
  powershell -ExecutionPolicy Bypass -File scripts\finalize_release.ps1
  powershell -ExecutionPolicy Bypass -File scripts\finalize_release.ps1 -Mode Draft
  powershell -ExecutionPolicy Bypass -File scripts\finalize_release.ps1 -Mode Publish
#>

[CmdletBinding()]
param(
    [ValidateSet("Validate", "Draft", "Publish")]
    [string]$Mode = "Validate",

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.7.9",

    [string]$Repository = "GrihmLord/DupeZ",

    [string]$Tag = "",

    [switch]$AllowNonMainValidation
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

        [Parameter(Mandatory = $false)]
        [string]$Description = $FilePath
    )

    Write-Host "`n=== $Description ==="
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Resolve-Executable {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Candidates,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    foreach ($candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "$Name was not found."
}

function Assert-SecretPathOutsideRepository {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Name is not configured."
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name does not exist at the configured path."
    }

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $relative = [System.IO.Path]::GetRelativePath($repoRoot, $resolved)
    if (
        -not $relative.StartsWith("..") -and
        -not [System.IO.Path]::IsPathRooted($relative)
    ) {
        throw "$Name must be stored outside the repository."
    }
    return $resolved
}

function Get-ReleaseArtifacts {
    param([string]$ResolvedVersion)

    $names = @(
        "DupeZ-GPU.exe",
        "DupeZ-Compat.exe",
        "DupeZ_v${ResolvedVersion}_Setup.exe",
        "DupeZ_Setup.exe",
        "DupeZ_Setup.exe.manifest.json",
        "DupeZ_Setup.exe.manifest.sig",
        "DupeZ.sbom.json",
        "DupeZ.vex.json",
        "binary-provenance.json"
    )
    return @(
        foreach ($name in $names) {
            $path = Join-Path $repoRoot "dist\$name"
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                throw "Required release artifact missing: dist\$name"
            }
            $item = Get-Item -LiteralPath $path
            if ($item.Length -le 0) {
                throw "Required release artifact is empty: dist\$name"
            }
            $item
        }
    )
}

function Assert-AuthenticodeReleaseArtifacts {
    param([System.IO.FileInfo[]]$Artifacts)

    $executableArtifacts = @(
        $Artifacts | Where-Object { $_.Extension -ieq ".exe" }
    )
    $records = @()
    foreach ($artifact in $executableArtifacts) {
        $signature = Get-AuthenticodeSignature -LiteralPath $artifact.FullName
        if ($signature.Status -ne "Valid") {
            throw "Authenticode validation failed for $($artifact.Name): $($signature.Status)"
        }
        if ($null -eq $signature.SignerCertificate) {
            throw "Authenticode signer certificate missing for $($artifact.Name)."
        }
        if ($null -eq $signature.TimeStamperCertificate) {
            throw "RFC3161 timestamp certificate missing for $($artifact.Name)."
        }
        $records += [ordered]@{
            name = $artifact.Name
            status = $signature.Status.ToString()
            signer_subject = $signature.SignerCertificate.Subject
            signer_thumbprint = $signature.SignerCertificate.Thumbprint
            timestamp_subject = $signature.TimeStamperCertificate.Subject
            timestamp_thumbprint = $signature.TimeStamperCertificate.Thumbprint
        }
    }
    return $records
}

function Resolve-MpCmdRun {
    $platformRoot = Join-Path $env:ProgramData "Microsoft\Windows Defender\Platform"
    $platformCandidates = @(
        Get-ChildItem -Path $platformRoot -Filter MpCmdRun.exe -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -ExpandProperty FullName
    )
    $legacy = Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
    return Resolve-Executable -Candidates (@($platformCandidates) + @($legacy)) -Name "Microsoft Defender MpCmdRun.exe"
}

function Invoke-DefenderReleaseScan {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo[]]$Artifacts
    )

    Write-Host "`n=== MICROSOFT DEFENDER RELEASE SCAN ==="
    $status = Get-MpComputerStatus
    if (-not $status.AntivirusEnabled) {
        throw "Microsoft Defender Antivirus is not enabled."
    }
    if (-not $status.RealTimeProtectionEnabled) {
        throw "Microsoft Defender real-time protection is not enabled."
    }

    try {
        Update-MpSignature | Out-Null
    }
    catch {
        Write-Warning "Defender signature update failed; checking installed signature age."
    }

    $status = Get-MpComputerStatus
    $signatureAge = (Get-Date) - $status.AntivirusSignatureLastUpdated
    if ($signatureAge.TotalHours -gt 48) {
        throw "Defender antivirus signatures are older than 48 hours."
    }

    $mpCmdRun = Resolve-MpCmdRun
    $logPath = Join-Path $repoRoot "dist\DefenderScan.txt"
    Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue

    foreach ($artifact in $Artifacts) {
        $output = & $mpCmdRun `
            -Scan `
            -ScanType 3 `
            -File $artifact.FullName `
            -DisableRemediation `
            -ReturnHR 2>&1
        $exitCode = $LASTEXITCODE
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value @(
            "[$([DateTime]::UtcNow.ToString('o'))] $($artifact.Name)",
            ($output | Out-String),
            "exit_code=$exitCode",
            ""
        )
        if ($exitCode -ne 0) {
            throw "Defender custom scan failed for $($artifact.Name) with exit code $exitCode."
        }
    }

    return [ordered]@{
        engine_version = $status.AMEngineVersion
        product_version = $status.AMProductVersion
        signature_version = $status.AntivirusSignatureVersion
        signature_updated_utc = $status.AntivirusSignatureLastUpdated.ToUniversalTime().ToString("o")
        realtime_protection = [bool]$status.RealTimeProtectionEnabled
        scan_log = "DefenderScan.txt"
    }
}

function Write-ReleaseEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo[]]$Artifacts,

        [Parameter(Mandatory = $true)]
        [object[]]$Authenticode,

        [Parameter(Mandatory = $true)]
        [object]$Defender,

        [Parameter(Mandatory = $true)]
        [string]$Commit
    )

    $hashRecords = @(
        foreach ($artifact in ($Artifacts | Sort-Object Name)) {
            $hash = Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256
            [ordered]@{
                name = $artifact.Name
                size = [int64]$artifact.Length
                sha256 = $hash.Hash.ToLowerInvariant()
            }
        }
    )

    $sumPath = Join-Path $repoRoot "dist\SHA256SUMS.txt"
    $sumLines = @(
        foreach ($record in $hashRecords) {
            "$($record.sha256)  $($record.name)"
        }
    )
    Set-Content -LiteralPath $sumPath -Encoding ASCII -Value $sumLines

    $attestation = [ordered]@{
        schema = "dupez.release-attestation.v1"
        product = "DupeZ"
        version = $Version
        commit = $Commit
        generated_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        builder = [ordered]@{
            machine = $env:COMPUTERNAME
            windows = [Environment]::OSVersion.VersionString
            powershell = $PSVersionTable.PSVersion.ToString()
        }
        artifacts = $hashRecords
        authenticode = $Authenticode
        defender = $Defender
        updater_manifest = [ordered]@{
            filename = "DupeZ_Setup.exe.manifest.json"
            signature = "DupeZ_Setup.exe.manifest.sig"
            pinned_key_fingerprint = "4e9c3c6731efbaa8"
        }
    }
    $attestationPath = Join-Path $repoRoot "dist\release-attestation.json"
    $attestation | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $attestationPath -Encoding UTF8

    return @(
        Get-Item -LiteralPath $sumPath,
        Get-Item -LiteralPath $attestationPath,
        Get-Item -LiteralPath (Join-Path $repoRoot "dist\DefenderScan.txt")
    )
}

function Invoke-GitHubReleaseStage {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo[]]$Assets,

        [Parameter(Mandatory = $true)]
        [string]$Commit
    )

    $gh = Resolve-Executable -Candidates @("gh") -Name "GitHub CLI"
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and [string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
        throw "GITHUB_TOKEN or GH_TOKEN is required for Draft/Publish mode."
    }

    $resolvedTag = if ($Tag) { $Tag } else { "v$Version" }
    $notes = Join-Path $repoRoot "docs\release-notes\v$Version.md"
    if (-not (Test-Path -LiteralPath $notes -PathType Leaf)) {
        throw "Release notes missing: docs\release-notes\v$Version.md"
    }

    $releaseJson = & $gh release view $resolvedTag --repo $Repository --json isDraft,tagName 2>$null
    $releaseExists = $LASTEXITCODE -eq 0
    if ($releaseExists) {
        $release = $releaseJson | ConvertFrom-Json
        if (-not $release.isDraft) {
            throw "Release $resolvedTag is already published; refusing to replace immutable assets."
        }
    }
    else {
        Invoke-Checked -FilePath $gh -Description "CREATE GITHUB DRAFT RELEASE" -ArgumentList @(
            "release", "create", $resolvedTag,
            "--repo", $Repository,
            "--draft",
            "--target", $Commit,
            "--title", "DupeZ v$Version",
            "--notes-file", $notes
        )
    }

    $uploadArguments = @("release", "upload", $resolvedTag, "--repo", $Repository, "--clobber")
    $uploadArguments += @($Assets | ForEach-Object { $_.FullName })
    Invoke-Checked -FilePath $gh -Description "UPLOAD VERIFIED DRAFT RELEASE ASSETS" -ArgumentList $uploadArguments

    if ($Mode -eq "Publish") {
        Invoke-Checked -FilePath $gh -Description "PUBLISH VERIFIED RELEASE" -ArgumentList @(
            "release", "edit", $resolvedTag,
            "--repo", $Repository,
            "--draft=false",
            "--latest"
        )
    }
}

Write-Host "============================================"
Write-Host " DupeZ v$Version Strict Release Finalizer"
Write-Host " Mode: $Mode"
Write-Host "============================================"

if ($Tag -and $Tag -ne "v$Version") {
    throw "Tag must be v$Version for this release."
}

$git = Resolve-Executable -Candidates @("git") -Name "Git"
$python = Resolve-Executable -Candidates @(
    (Join-Path $repoRoot ".venv\Scripts\python.exe")
) -Name "repository Python 3.11.9"
$signtool = Resolve-Executable -Candidates @("signtool") -Name "Windows SDK SignTool"
$iscc = Resolve-Executable -Candidates @(
    $env:DUPEZ_ISCC,
    "iscc",
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) -Name "Inno Setup ISCC.exe"

$signingCertificate = Assert-SecretPathOutsideRepository -Path $env:DUPEZ_SIGN_CERT -Name "DUPEZ_SIGN_CERT"
$updaterPrivateKey = Assert-SecretPathOutsideRepository -Path $env:DUPEZ_SIGN_PRIVKEY -Name "DUPEZ_SIGN_PRIVKEY"
$env:DUPEZ_SIGN_CERT = $signingCertificate
$env:DUPEZ_SIGN_PRIVKEY = $updaterPrivateKey
$env:DUPEZ_ISCC = $iscc

$currentBranch = (& $git branch --show-current).Trim()
$commit = (& $git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $commit) {
    throw "Could not resolve the current Git commit."
}
if (@(& $git status --porcelain).Count -ne 0) {
    & $git status --short
    throw "Repository must be clean before a release build."
}
if ($Mode -ne "Validate" -and $currentBranch -ne "main") {
    throw "Draft/Publish mode must run from main; current branch is $currentBranch."
}
if ($Mode -eq "Validate" -and -not $AllowNonMainValidation -and $currentBranch -ne "main") {
    throw "Validation defaults to main. Pass -AllowNonMainValidation only for a pre-merge candidate."
}

Invoke-Checked -FilePath $python -Description "VERIFY RELEASE PYTHON" -ArgumentList @(
    "-I", "-S", "-c",
    "import struct,sys; raise SystemExit(0 if sys.version_info[:3]==(3,11,9) and struct.calcsize('P')==8 else 1)"
)
Invoke-Checked -FilePath $python -Description "SOURCE RELEASE PREFLIGHT" -ArgumentList @(
    "-I", "scripts\release_preflight.py", "--version", $Version
)

$env:DUPEZ_RELEASE_STRICT = "1"
Invoke-Checked -FilePath (Join-Path $repoRoot "packaging\build_variants.bat") -Description "BUILD AND SIGN RELEASE ARTIFACTS"

$artifacts = Get-ReleaseArtifacts -ResolvedVersion $Version
$authenticode = Assert-AuthenticodeReleaseArtifacts -Artifacts $artifacts
$defender = Invoke-DefenderReleaseScan -Artifacts $artifacts

Invoke-Checked -FilePath $python -Description "FINAL DIST RELEASE PREFLIGHT" -ArgumentList @(
    "-I", "scripts\release_preflight.py",
    "--version", $Version,
    "--dist"
)

$evidence = Write-ReleaseEvidence -Artifacts $artifacts -Authenticode $authenticode -Defender $defender -Commit $commit
$releaseAssets = @($artifacts) + @($evidence)

if ($Mode -in @("Draft", "Publish")) {
    Invoke-GitHubReleaseStage -Assets $releaseAssets -Commit $commit
}

Write-Host "`nSTRICT RELEASE FINALIZATION: PASS" -ForegroundColor Green
Write-Host "Commit: $commit"
Write-Host "Artifacts: $($releaseAssets.Count)"
Write-Host "Mode: $Mode"
