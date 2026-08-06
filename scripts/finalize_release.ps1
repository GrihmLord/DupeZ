#requires -Version 5.1
<#+
.SYNOPSIS
Build, sign, scan, and attest DupeZ release artifacts on the protected Windows
signing host.

.DESCRIPTION
The Ed25519 private key matching the updater public key pinned in
app/core/update_verify.py must exist outside the repository. Authenticode also
requires an external PFX unless -AllowUnsigned is explicitly selected. This
script never generates, exports, uploads, or prints either key.
#>

[CmdletBinding()]
param(
    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version = "5.7.9",

    [switch]$AllowNonMainValidation,

    [switch]$AllowUnsigned
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

function Resolve-Tool {
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

function Get-WindowsSdkSignToolCandidates {
    $sdkRoots = @()
    if (${env:ProgramFiles(x86)}) {
        $sdkRoots += Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    }
    if ($env:ProgramFiles) {
        $sdkRoots += Join-Path $env:ProgramFiles "Windows Kits\10\bin"
    }

    $candidates = @()
    foreach ($sdkRoot in $sdkRoots) {
        if (-not (Test-Path -LiteralPath $sdkRoot -PathType Container)) {
            continue
        }
        $candidates += @(
            Get-ChildItem `
                -Path (Join-Path $sdkRoot "*\x64\signtool.exe") `
                -File `
                -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending |
                Select-Object -ExpandProperty FullName
        )
    }
    return @($candidates | Select-Object -Unique)
}

function Require-ExternalSecretFile {
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Name is not configured."
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name does not reference an existing file."
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $repoPrefix = $repoRoot.TrimEnd('\') + '\'
    if ($resolved.StartsWith(
        $repoPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "$Name must be stored outside the repository."
    }
    return $resolved
}

function Resolve-EnvVar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    $value = [Environment]::GetEnvironmentVariable($Name, "User")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    $value = [Environment]::GetEnvironmentVariable($Name, "Machine")
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    return ""
}

function Get-RequiredArtifacts {
    param([string]$ReleaseVersion)

    $names = @(
        "DupeZ-GPU.exe",
        "DupeZ-Compat.exe",
        "DupeZ_v${ReleaseVersion}_Setup.exe",
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

function Test-AuthenticodeArtifacts {
    param(
        [System.IO.FileInfo[]]$Artifacts,
        [string]$SignTool
    )

    $records = @()
    foreach ($artifact in @($Artifacts | Where-Object { $_.Extension -ieq ".exe" })) {
        & $SignTool verify /pa /all /tw /q $artifact.FullName
        if ($LASTEXITCODE -ne 0) {
            throw (
                "SignTool verification failed for $($artifact.Name) with " +
                "exit code $LASTEXITCODE."
            )
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $artifact.FullName
        if ($signature.Status -ne "Valid") {
            throw "Authenticode validation failed for $($artifact.Name): $($signature.Status)"
        }
        if ($null -eq $signature.SignerCertificate) {
            throw "Signer certificate missing for $($artifact.Name)."
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

function Get-UnsignedAuthenticodeRecords {
    param([System.IO.FileInfo[]]$Artifacts)

    return @(
        foreach ($artifact in @($Artifacts | Where-Object { $_.Extension -ieq ".exe" })) {
            [ordered]@{
                name = $artifact.Name
                status = "Unsigned"
                signer_subject = $null
                signer_thumbprint = $null
                timestamp_subject = $null
                timestamp_thumbprint = $null
            }
        }
    )
}

function Resolve-MpCmdRun {
    $platformRoot = Join-Path $env:ProgramData "Microsoft\Windows Defender\Platform"
    $candidates = @(
        Get-ChildItem -Path $platformRoot -Filter MpCmdRun.exe -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -ExpandProperty FullName
    )
    $candidates += Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
    return Resolve-Tool -Candidates $candidates -Name "Microsoft Defender MpCmdRun.exe"
}

function Invoke-DefenderScan {
    param([System.IO.FileInfo[]]$Artifacts)

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
        Write-Warning "Defender signature update failed; installed signature age will be enforced."
    }
    $status = Get-MpComputerStatus
    $age = (Get-Date) - $status.AntivirusSignatureLastUpdated
    if ($age.TotalHours -gt 48) {
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
            throw "Defender scan failed for $($artifact.Name) with exit code $exitCode."
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
        [System.IO.FileInfo[]]$Artifacts,
        [object[]]$Authenticode,
        [object]$Defender,
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
    Set-Content -LiteralPath $sumPath -Encoding ASCII -Value @(
        foreach ($record in $hashRecords) {
            "$($record.sha256)  $($record.name)"
        }
    )

    $attestation = [ordered]@{
        schema = "dupez.release-attestation.v1"
        product = "DupeZ"
        version = $Version
        commit = $Commit
        generated_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        distribution_signing_mode = if ($AllowUnsigned) { "unsigned" } else { "authenticode" }
        artifacts = $hashRecords
        authenticode = $Authenticode
        defender = $Defender
        updater_manifest = [ordered]@{
            filename = "DupeZ_Setup.exe.manifest.json"
            signature = "DupeZ_Setup.exe.manifest.sig"
            pinned_key_fingerprint = "5555f0e8c31a40ed" # pragma: allowlist secret
        }
    }
    $attestation | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath (Join-Path $repoRoot "dist\release-attestation.json") -Encoding UTF8
}

Write-Host "============================================"
Write-Host " DupeZ v$Version Strict Release Finalizer"
Write-Host "============================================"

$isAdmin = (
    New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Release finalization must run from Administrator PowerShell."
}

$git = Resolve-Tool -Candidates @("git") -Name "Git"
$python = Resolve-Tool -Candidates @(
    (Join-Path $repoRoot ".venv\Scripts\python.exe")
) -Name "repository Python 3.11.9"
$signTool = $null
if (-not $AllowUnsigned) {
    $signToolCandidates = @($env:DUPEZ_SIGNTOOL, "signtool")
    $signToolCandidates += Get-WindowsSdkSignToolCandidates
    $signTool = Resolve-Tool `
        -Candidates $signToolCandidates `
        -Name "Windows SDK SignTool"
}
$isccCandidates = @()
if ($env:DUPEZ_ISCC) {
    $isccCandidates += $env:DUPEZ_ISCC
}
$isccCandidates += "iscc"
if (${env:ProgramFiles(x86)}) {
    $isccCandidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if ($env:ProgramFiles) {
    $isccCandidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
}
$iscc = Resolve-Tool -Candidates $isccCandidates -Name "Inno Setup ISCC.exe"

if ($AllowUnsigned) {
    $env:DUPEZ_SIGN_CERT = ""
    $env:DUPEZ_SIGN_PASS = ""
}
else {
    $env:DUPEZ_SIGN_CERT = Require-ExternalSecretFile -Path (Resolve-EnvVar -Name "DUPEZ_SIGN_CERT") -Name "DUPEZ_SIGN_CERT"
}
$env:DUPEZ_SIGN_PRIVKEY = Require-ExternalSecretFile -Path (Resolve-EnvVar -Name "DUPEZ_SIGN_PRIVKEY") -Name "DUPEZ_SIGN_PRIVKEY"
if ($signTool) {
    $env:DUPEZ_SIGNTOOL = $signTool
}
$env:DUPEZ_ISCC = $iscc
$env:DUPEZ_RELEASE_STRICT = "1"

$branch = (& $git branch --show-current).Trim()
$commit = (& $git rev-parse HEAD).Trim()
if (@(& $git status --porcelain).Count -ne 0) {
    & $git status --short
    throw "Repository must be clean before a release build."
}
if (-not $AllowNonMainValidation -and $branch -ne "main") {
    throw "Release finalization must run from main; current branch is $branch."
}

Invoke-Checked -FilePath $python -Description "VERIFY RELEASE PYTHON" -ArgumentList @(
    "-I", "-S", "-c",
    "import struct,sys; raise SystemExit(0 if sys.version_info[:3]==(3,11,9) and struct.calcsize('P')==8 else 1)"
)
Invoke-Checked -FilePath $python -Description "SOURCE RELEASE PREFLIGHT" -ArgumentList @(
    "-I", "scripts\release_preflight.py", "--version", $Version
)
Invoke-Checked -FilePath (Join-Path $repoRoot "packaging\build_variants.bat") -Description "BUILD RELEASE ARTIFACTS"

$artifacts = Get-RequiredArtifacts -ReleaseVersion $Version
$authenticode = if ($AllowUnsigned) {
    Get-UnsignedAuthenticodeRecords -Artifacts $artifacts
}
else {
    Test-AuthenticodeArtifacts -Artifacts $artifacts -SignTool $signTool
}
$defender = Invoke-DefenderScan -Artifacts $artifacts

$distPython = Resolve-Tool -Candidates @(
    (Join-Path $repoRoot ".build-venv\Scripts\python.exe")
) -Name "release build Python"
$preflightArguments = @("-I", "scripts\release_preflight.py", "--version", $Version, "--dist")
if ($AllowUnsigned) {
    $preflightArguments += "--allow-unsigned"
}
Invoke-Checked -FilePath $distPython -Description "FINAL DIST RELEASE PREFLIGHT" -ArgumentList $preflightArguments
Write-ReleaseEvidence -Artifacts $artifacts -Authenticode $authenticode -Defender $defender -Commit $commit

Write-Host "`nSTRICT RELEASE FINALIZATION: PASS" -ForegroundColor Green
Write-Host "Commit: $commit"
Write-Host "Artifacts: $($artifacts.Count)"
Write-Host "Distribution signing mode: $(if ($AllowUnsigned) { 'UNSIGNED' } else { 'Authenticode' })"
