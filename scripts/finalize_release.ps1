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
    [string]$Version = "5.8.0",

    [switch]$AllowNonMainValidation,

    [switch]$AllowUnsigned
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "release_git_contract.ps1")

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

function Resolve-ReleaseBootstrapPython {
    param(
        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$ConfiguredPath = ""
    )

    # Use the same explicit override/default as build_variants.bat. Never
    # silently fall back to another interpreter after an invalid override.
    $candidate = $ConfiguredPath
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        throw "DUPEZ_BOOTSTRAP_PYTHON must be an absolute executable path."
    }
    if (
        -not (Test-Path -LiteralPath $candidate -PathType Leaf) -or
        [System.IO.Path]::GetExtension($candidate) -ine ".exe"
    ) {
        throw "Configured repository Python 3.13.14 x64 executable was not found."
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).ProviderPath
    $buildVenvPrefix = (
        [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".release-venv"))
    ).TrimEnd('\') + '\'
    if ($resolved.StartsWith(
        $buildVenvPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Bootstrap Python must not be inside the disposable .release-venv."
    }

    Invoke-Checked -FilePath $resolved -Description "VERIFY RELEASE PYTHON" -ArgumentList @(
        "-I", "-S", "-c",
        "import struct,sys; raise SystemExit(0 if sys.version_info[:3]==(3,13,14) and struct.calcsize('P')==8 else 1)"
    )
    return $resolved
}

function Read-ReleaseToolPins {
    $path = Join-Path $repoRoot "packaging\release-tools.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Pinned release tool manifest is missing."
    }
    $item = Get-Item -LiteralPath $path -Force
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Pinned release tool manifest must not be a reparse point."
    }
    try {
        $raw = Get-Content -LiteralPath $path -Raw
        if (
            [string]::IsNullOrWhiteSpace($raw) -or
            -not $raw.TrimStart().StartsWith(
                "{",
                [StringComparison]::Ordinal
            )
        ) {
            throw "root must be a JSON object"
        }
        $pins = $raw | ConvertFrom-Json
    }
    catch {
        throw "Pinned release tool manifest is malformed."
    }
    $rootNames = @($pins.PSObject.Properties.Name | Sort-Object)
    $expectedRootNames = @("iscc", "schema", "signtool")
    if (
        $pins -isnot [System.Management.Automation.PSCustomObject] -or
        @(
            Compare-Object `
                -ReferenceObject $expectedRootNames `
                -DifferenceObject $rootNames
        ).Count -ne 0 -or
        $pins.schema -cne "dupez.release-tools.v1"
    ) {
        throw "Pinned release tool manifest schema is invalid."
    }
    return $pins
}

function Test-PinnedProductVersion {
    param(
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [AllowEmptyString()]
        [string]$ActualVersion,

        [Parameter(Mandatory = $true)]
        [string]$PinnedVersion
    )

    if ([string]::IsNullOrWhiteSpace($ActualVersion)) {
        return $false
    }
    return $ActualVersion.Trim() -ceq $PinnedVersion
}

function Resolve-PinnedReleaseTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [object]$Pin,

        [Parameter(Mandatory = $false)]
        [AllowEmptyString()]
        [string]$ConfiguredPath = ""
    )

    foreach ($property in @(
        "version",
        "default_base",
        "relative_path",
        "sha256",
        "signer_certificate_sha256",
        "signer_subject",
        "signer_thumbprint"
    )) {
        if (
            $property -notin @($Pin.PSObject.Properties.Name) -or
            [string]::IsNullOrWhiteSpace([string]$Pin.$property)
        ) {
            throw "$Name pin is incomplete."
        }
    }
    if (
        [string]$Pin.default_base -cne "ProgramFilesX86" -or
        [System.IO.Path]::IsPathRooted([string]$Pin.relative_path) -or
        [string]$Pin.relative_path -match '[*?]' -or
        @([string]$Pin.relative_path -split '[\\/]' | Where-Object {
            $_ -in @(".", "..")
        }).Count -ne 0 -or
        [string]$Pin.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$Pin.signer_certificate_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [string]$Pin.signer_thumbprint -cnotmatch '^[0-9a-f]{40}$'
    ) {
        throw "$Name pin failed strict validation."
    }

    if ($Name -ceq "Windows SDK SignTool") {
        if (
            "sdk_version" -notin @($Pin.PSObject.Properties.Name) -or
            [string]$Pin.version -cnotmatch '^\d+\.\d+\.\d+\.\d+$' -or
            [string]$Pin.sdk_version -cnotmatch '^\d+\.\d+\.\d+\.\d+$' -or
            [string]$Pin.relative_path -cne (
                "Windows Kits\10\bin\{0}\x64\signtool.exe" -f
                [string]$Pin.sdk_version
            )
        ) {
            throw "$Name pin failed strict validation."
        }
    }
    elseif ($Name -ceq "Inno Setup ISCC.exe") {
        if (
            [string]$Pin.version -cnotmatch '^\d+\.\d+\.\d+$' -or
            [string]$Pin.relative_path -cne "Inno Setup 6\ISCC.exe"
        ) {
            throw "$Name pin failed strict validation."
        }
    }
    else {
        throw "Unknown pinned release tool requested."
    }

    $candidate = $ConfiguredPath
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        if ([string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
            throw "$Name default base directory is unavailable."
        }
        $candidate = Join-Path `
            ${env:ProgramFiles(x86)} `
            ([string]$Pin.relative_path)
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        throw "$Name must resolve from an absolute path."
    }
    if ([string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        throw "$Name default base directory is unavailable."
    }
    $expectedPath = [System.IO.Path]::GetFullPath((
        Join-Path ${env:ProgramFiles(x86)} ([string]$Pin.relative_path)
    ))
    $candidate = [System.IO.Path]::GetFullPath($candidate)
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals(
        $candidate,
        $expectedPath
    )) {
        throw "$Name path does not match the repository pin."
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "$Name pinned executable is unavailable."
    }
    $item = Get-Item -LiteralPath $candidate -Force
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "$Name pinned executable must not be a reparse point."
    }
    $actualHash = (
        Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualHash -cne [string]$Pin.sha256) {
        throw "$Name executable hash does not match the repository pin."
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $item.FullName
    if (
        $signature.Status -ne "Valid" -or
        $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -cne [string]$Pin.signer_subject -or
        $signature.SignerCertificate.Thumbprint.ToLowerInvariant() -cne
            [string]$Pin.signer_thumbprint
    ) {
        throw "$Name Authenticode identity does not match the repository pin."
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $certificateSha256 = -join @(
            $sha256.ComputeHash($signature.SignerCertificate.RawData) |
                ForEach-Object { $_.ToString("x2") }
        )
    }
    finally {
        $sha256.Dispose()
    }
    if ($certificateSha256 -cne [string]$Pin.signer_certificate_sha256) {
        throw "$Name signer certificate does not match the repository pin."
    }

    if ($Name -ceq "Windows SDK SignTool") {
        if (
            $item.VersionInfo.ProductVersion -cne [string]$Pin.version -or
            [System.IO.Path]::GetFileName($item.FullName) -cne "signtool.exe"
        ) {
            throw "$Name version does not match the repository pin."
        }
    }
    elseif ($Name -ceq "Inno Setup ISCC.exe") {
        $versionCarrierPath = Join-Path $item.DirectoryName "unins000.exe"
        if (-not (Test-Path -LiteralPath $versionCarrierPath -PathType Leaf)) {
            throw "$Name version evidence is unavailable."
        }
        $versionCarrier = Get-Item -LiteralPath $versionCarrierPath -Force
        if (
            ($versionCarrier.Attributes -band
                [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-PinnedProductVersion `
                -ActualVersion ([string]$versionCarrier.VersionInfo.ProductVersion) `
                -PinnedVersion ([string]$Pin.version))
        ) {
            throw "$Name installed version does not match the repository pin."
        }
    }
    return $item.FullName
}

function New-ExactSourceArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReleaseVersion,

        [Parameter(Mandatory = $true)]
        [string]$Commit
    )

    if ($Commit -cnotmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
        throw "Source archive commit is invalid."
    }
    $distRoot = Join-Path $repoRoot "dist"
    Assert-ReleasePathIsNonReparse -Path $distRoot -RequireLeaf
    if (-not (Test-Path -LiteralPath $distRoot -PathType Container)) {
        throw "Distribution directory is unavailable for source archive creation."
    }
    $archiveName = "DupeZ-v${ReleaseVersion}-source.zip"
    $archivePath = Join-Path $distRoot $archiveName
    if (Test-Path -LiteralPath $archivePath) {
        $existing = Get-Item -LiteralPath $archivePath -Force
        if (
            $existing.PSIsContainer -or
            ($existing.Attributes -band
                [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "Refusing an unsafe existing source archive path."
        }
        Remove-Item -LiteralPath $archivePath -Force
    }
    if (Test-Path -LiteralPath $archivePath) {
        throw "Could not remove the stale source archive."
    }

    Invoke-TrustedReleaseGit `
        -RepositoryRoot $repoRoot `
        -Arguments @(
            "archive",
            "--format=zip",
            "--prefix=DupeZ-v${ReleaseVersion}/",
            "--output=$archivePath",
            $Commit
        ) | Out-Null

    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "Trusted Git did not create the release source archive."
    }
    Assert-ReleasePathIsNonReparse -Path $archivePath -RequireLeaf
    $archive = Get-Item -LiteralPath $archivePath -Force
    if ($archive.Length -le 0) {
        throw "Release source archive is empty."
    }
    return $archive
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
        "DupeZ.vulnerability-review.json",
        "binary-provenance.json",
        "LICENSE.txt",
        "SOURCE_AND_RELINK.txt",
        "THIRD_PARTY_NOTICES.txt",
        "license-payload.json",
        "DupeZ-v${ReleaseVersion}-source.zip"
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
        [string]$SignTool,
        [object]$SignToolPin
    )

    $records = @()
    foreach ($artifact in @($Artifacts | Where-Object { $_.Extension -ieq ".exe" })) {
        $verifiedSignTool = Resolve-PinnedReleaseTool `
            -Name "Windows SDK SignTool" `
            -Pin $SignToolPin `
            -ConfiguredPath $SignTool
        & $verifiedSignTool verify /pa /all /tw /q $artifact.FullName
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
        [string]$Commit,
        [string]$UpdaterSignerFingerprint
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
            verified_key_fingerprint = $UpdaterSignerFingerprint
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

$python = Resolve-ReleaseBootstrapPython `
    -ConfiguredPath (Resolve-EnvVar -Name "DUPEZ_BOOTSTRAP_PYTHON")
# Keep source validation and the fresh build environment on the exact same
# verified interpreter, including when the override came from User/Machine.
$env:DUPEZ_BOOTSTRAP_PYTHON = $python
$releaseToolPins = Read-ReleaseToolPins
$signTool = $null
if (-not $AllowUnsigned) {
    $signTool = Resolve-PinnedReleaseTool `
        -Name "Windows SDK SignTool" `
        -Pin $releaseToolPins.signtool `
        -ConfiguredPath (Resolve-EnvVar -Name "DUPEZ_SIGNTOOL")
}
$iscc = Resolve-PinnedReleaseTool `
    -Name "Inno Setup ISCC.exe" `
    -Pin $releaseToolPins.iscc `
    -ConfiguredPath (Resolve-EnvVar -Name "DUPEZ_ISCC")

if ($AllowUnsigned) {
    $env:DUPEZ_SIGN_CERT = ""
    $env:DUPEZ_SIGN_PASS = ""
    $env:DUPEZ_ALLOW_UNSIGNED = "1"
}
else {
    $env:DUPEZ_SIGN_CERT = Require-ExternalSecretFile -Path (Resolve-EnvVar -Name "DUPEZ_SIGN_CERT") -Name "DUPEZ_SIGN_CERT"
    $env:DUPEZ_ALLOW_UNSIGNED = "0"
}

function Get-VerifiedUpdaterSignerFingerprint {
    param([string]$ReleaseVersion)

    # FINAL DIST RELEASE PREFLIGHT cryptographically verifies this exact
    # envelope before this function is called. Attest the signer actually used
    # instead of a hardcoded value that can drift from the external key.
    $signaturePath = Join-Path $repoRoot "dist\DupeZ_Setup.exe.manifest.sig"
    [byte[]]$envelope = [System.IO.File]::ReadAllBytes($signaturePath)
    if ($envelope.Length -ne 72) {
        throw "Update signature envelope must be exactly 72 bytes."
    }
    $fingerprint = -join @(
        $envelope[0..7] | ForEach-Object { $_.ToString("x2") }
    )

    # v5.7.9 established the recovery key as the v5.8 update signer. Reject an
    # otherwise trusted retired-key signature rather than mis-attest it.
    if (
        $ReleaseVersion -eq "5.8.0" -and
        $fingerprint -ne "5555f0e8c31a40ed" # pragma: allowlist secret
    ) {
        throw (
            "DupeZ v5.8.0 must use recovery update signer " +
            "5555f0e8c31a40ed; verified envelope used $fingerprint."
        )
    }
    return $fingerprint
}
$env:DUPEZ_SIGN_PRIVKEY = Require-ExternalSecretFile -Path (Resolve-EnvVar -Name "DUPEZ_SIGN_PRIVKEY") -Name "DUPEZ_SIGN_PRIVKEY"
if ($signTool) {
    $env:DUPEZ_SIGNTOOL = $signTool
}
$env:DUPEZ_ISCC = $iscc
$env:DUPEZ_RELEASE_STRICT = "1"

$requiredBranch = if ($AllowNonMainValidation) { "" } else { "main" }
$sourceIdentity = Get-ReleaseGitIdentity `
    -RepositoryRoot $repoRoot `
    -RequiredBranch $requiredBranch
$branch = $sourceIdentity.Branch
$commit = $sourceIdentity.Commit

Invoke-Checked -FilePath $python -Description "SOURCE RELEASE PREFLIGHT" -ArgumentList @(
    "-I", "scripts\release_preflight.py", "--version", $Version
)
$env:DUPEZ_PORTABLE_ONLY = "0"
# Re-evaluate the complete identities at the build boundary. The batch pipeline
# then re-hashes each exact path immediately before every SignTool/ISCC use.
if (-not $AllowUnsigned) {
    $signTool = Resolve-PinnedReleaseTool `
        -Name "Windows SDK SignTool" `
        -Pin $releaseToolPins.signtool `
        -ConfiguredPath $signTool
    $env:DUPEZ_SIGNTOOL = $signTool
}
$iscc = Resolve-PinnedReleaseTool `
    -Name "Inno Setup ISCC.exe" `
    -Pin $releaseToolPins.iscc `
    -ConfiguredPath $iscc
$env:DUPEZ_ISCC = $iscc
Invoke-Checked -FilePath (Join-Path $repoRoot "packaging\build_variants.bat") -Description "BUILD RELEASE ARTIFACTS"
Assert-ReleaseGitIdentityUnchanged `
    -RepositoryRoot $repoRoot `
    -ExpectedCommit $commit `
    -RequiredBranch $branch | Out-Null

$sourceArchive = New-ExactSourceArchive `
    -ReleaseVersion $Version `
    -Commit $commit
Write-Host "Exact-commit source archive: $($sourceArchive.Name)"
Assert-ReleaseGitIdentityUnchanged `
    -RepositoryRoot $repoRoot `
    -ExpectedCommit $commit `
    -RequiredBranch $branch | Out-Null

$artifacts = Get-RequiredArtifacts -ReleaseVersion $Version
$signableNames = @(
    "DupeZ-GPU.exe",
    "DupeZ-Compat.exe",
    "DupeZ_v${Version}_Setup.exe",
    "DupeZ_Setup.exe"
)
$signableArtifacts = @(
    $artifacts | Where-Object { $_.Name -in $signableNames }
)
if ($signableArtifacts.Count -ne $signableNames.Count) {
    throw "Authenticode artifact selection is incomplete."
}
$authenticode = if ($AllowUnsigned) {
    Get-UnsignedAuthenticodeRecords -Artifacts $signableArtifacts
}
else {
    Test-AuthenticodeArtifacts `
        -Artifacts $signableArtifacts `
        -SignTool $signTool `
        -SignToolPin $releaseToolPins.signtool
}
$defender = Invoke-DefenderScan -Artifacts $artifacts

$distPython = Resolve-Tool -Candidates @(
    (Join-Path $repoRoot ".release-venv\Scripts\python.exe")
) -Name "release build Python"
$preflightArguments = @("-I", "scripts\release_preflight.py", "--version", $Version, "--dist")
if ($AllowUnsigned) {
    $preflightArguments += "--allow-unsigned"
}
Invoke-Checked -FilePath $distPython -Description "FINAL DIST RELEASE PREFLIGHT" -ArgumentList $preflightArguments
$updaterSignerFingerprint = Get-VerifiedUpdaterSignerFingerprint -ReleaseVersion $Version
Write-ReleaseEvidence -Artifacts $artifacts -Authenticode $authenticode -Defender $defender -Commit $commit -UpdaterSignerFingerprint $updaterSignerFingerprint

Write-Host "`nSTRICT RELEASE FINALIZATION: PASS" -ForegroundColor Green
Write-Host "Commit: $commit"
Write-Host "Artifacts: $($artifacts.Count)"
Write-Host "Distribution signing mode: $(if ($AllowUnsigned) { 'UNSIGNED' } else { 'Authenticode' })"
