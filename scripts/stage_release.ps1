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
    [string]$Version = "5.8.0",

    [string]$Repository = "GrihmLord/DupeZ",

    [switch]$AllowUnsigned
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
. (Join-Path $PSScriptRoot "manual_release_gate_contract.ps1")
. (Join-Path $PSScriptRoot "frozen_runtime_evidence_contract.ps1")
. (Join-Path $PSScriptRoot "release_git_contract.ps1")

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
    $stream = [System.IO.File]::OpenRead($Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($stream)
        return [System.BitConverter]::ToString($digest).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Assert-RegularFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description is missing: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "$Description must not be a reparse point: $Path"
    }
    return $item
}

function Copy-ReleaseAssetSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,

        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$Names
    )

    $destinationDirectory = Get-Item -LiteralPath $DestinationRoot -Force
    if (
        -not $destinationDirectory.PSIsContainer -or
        ($destinationDirectory.Attributes -band
            [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Release snapshot destination is not a regular directory."
    }

    $seen = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $snapshots = @()
    foreach ($name in $Names) {
        if (
            [string]::IsNullOrWhiteSpace($name) -or
            [System.IO.Path]::GetFileName($name) -cne $name -or
            -not $seen.Add($name)
        ) {
            throw "Release snapshot contains an unsafe or duplicate name: $name"
        }
        $sourcePath = Join-Path $SourceRoot $name
        $source = Assert-RegularFile `
            -Path $sourcePath `
            -Description "Required staged asset"
        if ($source.Length -le 0) {
            throw "Required staged asset is empty: $sourcePath"
        }
        $destinationPath = Join-Path $DestinationRoot $name
        $sourceStream = [System.IO.File]::Open(
            $source.FullName,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        try {
            $destinationStream = [System.IO.File]::Open(
                $destinationPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $sourceStream.CopyTo($destinationStream)
                $destinationStream.Flush($true)
            }
            finally {
                $destinationStream.Dispose()
            }
        }
        finally {
            $sourceStream.Dispose()
        }
        $snapshot = Assert-RegularFile `
            -Path $destinationPath `
            -Description "Snapshotted release asset"
        if ($snapshot.Length -ne $source.Length) {
            throw "Release snapshot copy length mismatch: $name"
        }
        $snapshots += $snapshot
    }
    return @($snapshots)
}

function Get-ReleaseAssetBinding {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Assets
    )

    $hashes = @{}
    $lengths = @{}
    foreach ($asset in $Assets) {
        $item = Assert-RegularFile `
            -Path $asset.FullName `
            -Description "Release binding asset"
        if ($hashes.ContainsKey($item.Name)) {
            throw "Release binding contains a duplicate asset: $($item.Name)"
        }
        $hashes[$item.Name] = Get-Sha256 -Path $item.FullName
        $lengths[$item.Name] = [int64]$item.Length
    }
    if ($hashes.Count -lt 1) {
        throw "Release binding contains no assets."
    }
    return [pscustomobject]@{
        Hashes = $hashes
        Lengths = $lengths
    }
}

function Assert-ReleaseAssetBinding {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Assets,

        [Parameter(Mandatory = $true)]
        [hashtable]$Hashes,

        [Parameter(Mandatory = $true)]
        [hashtable]$Lengths,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (
        $Assets.Count -ne $Hashes.Count -or
        $Assets.Count -ne $Lengths.Count
    ) {
        throw "$Description asset inventory does not match its binding."
    }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($asset in $Assets) {
        $item = Assert-RegularFile `
            -Path $asset.FullName `
            -Description $Description
        if (
            -not $seen.Add($item.Name) -or
            -not $Hashes.ContainsKey($item.Name) -or
            -not $Lengths.ContainsKey($item.Name)
        ) {
            throw "$Description inventory mismatch: $($item.Name)"
        }
        if ([int64]$item.Length -ne [int64]$Lengths[$item.Name]) {
            throw "$Description size mismatch for $($item.Name)."
        }
        if ((Get-Sha256 -Path $item.FullName) -cne $Hashes[$item.Name]) {
            if ($Description -ceq "Downloaded release") {
                throw "Downloaded release SHA-256 mismatch for $($item.Name)."
            }
            throw "$Description SHA-256 mismatch for $($item.Name)."
        }
    }
}

function Open-ReleaseAssetReadLocks {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Assets
    )

    $locks = @()
    try {
        foreach ($asset in $Assets) {
            $item = Assert-RegularFile `
                -Path $asset.FullName `
                -Description "Release snapshot lock target"
            $locks += [System.IO.File]::Open(
                $item.FullName,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
        }
        return @($locks)
    }
    catch {
        foreach ($lock in $locks) {
            $lock.Dispose()
        }
        throw
    }
}

function Invoke-GhAttestationVerification {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GhPath,

        [Parameter(Mandatory = $true)]
        [object]$Asset,

        [Parameter(Mandatory = $true)]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [string]$SignerWorkflow,

        [Parameter(Mandatory = $true)]
        [string]$SourceCommit,

        [Parameter(Mandatory = $true)]
        [string]$PredicateType,

        [Parameter(Mandatory = $true)]
        [string]$AttestationKind
    )

    $item = Assert-RegularFile `
        -Path $Asset.FullName `
        -Description "GitHub attestation subject"
    $arguments = @(
        "attestation", "verify", $item.FullName,
        "--repo", $Repository,
        "--signer-workflow", $SignerWorkflow,
        "--signer-digest", $SourceCommit,
        "--source-ref", "refs/heads/main",
        "--source-digest", $SourceCommit,
        "--predicate-type", $PredicateType,
        "--format", "json",
        "--jq", "length"
    )

    # Verification output can contain local paths and workflow-controlled
    # predicate data. Suppress it and accept only a positive JSON result count.
    $resultLines = @(& $GhPath @arguments 2>$null)
    $exitCode = $LASTEXITCODE
    $resultText = (@($resultLines) -join "").Trim()
    $matchCount = 0
    $hasNumericResult = [int]::TryParse($resultText, [ref]$matchCount)
    if (
        $exitCode -ne 0 -or
        -not $hasNumericResult -or
        $matchCount -lt 1
    ) {
        throw (
            "GitHub $AttestationKind attestation verification failed for " +
            "$($item.Name)."
        )
    }
}

function Assert-GitHubArtifactAttestations {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GhPath,

        [Parameter(Mandatory = $true)]
        [object[]]$Assets,

        [Parameter(Mandatory = $true)]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [string]$SignerWorkflow,

        [Parameter(Mandatory = $true)]
        [string]$SourceCommit,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Host "`n=== $Description ==="
    $assetNames = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $publishableExecutables = @()
    $sbomAssets = @()
    foreach ($asset in $Assets) {
        $item = Assert-RegularFile `
            -Path $asset.FullName `
            -Description "GitHub attestation inventory subject"
        if (-not $assetNames.Add($item.Name)) {
            throw "GitHub attestation inventory contains a duplicate asset."
        }
        if ($item.Extension -ieq ".exe") {
            $publishableExecutables += $item
        }
        if ($item.Name -ceq "DupeZ.sbom.json") {
            $sbomAssets += $item
        }
    }
    if ($publishableExecutables.Count -lt 1) {
        throw "GitHub attestation inventory contains no executable subjects."
    }
    if ($sbomAssets.Count -ne 1) {
        throw "GitHub attestation inventory must contain exactly one SBOM asset."
    }

    # The protected workflows create provenance for the publishable executables
    # and SBOM file, then attach the CycloneDX SBOM to every executable subject.
    $provenanceSubjects = @($publishableExecutables) + @($sbomAssets)
    foreach ($subject in $provenanceSubjects) {
        Invoke-GhAttestationVerification `
            -GhPath $GhPath `
            -Asset $subject `
            -Repository $Repository `
            -SignerWorkflow $SignerWorkflow `
            -SourceCommit $SourceCommit `
            -PredicateType "https://slsa.dev/provenance/v1" `
            -AttestationKind "provenance"
    }
    foreach ($subject in $publishableExecutables) {
        Invoke-GhAttestationVerification `
            -GhPath $GhPath `
            -Asset $subject `
            -Repository $Repository `
            -SignerWorkflow $SignerWorkflow `
            -SourceCommit $SourceCommit `
            -PredicateType "https://cyclonedx.org/bom" `
            -AttestationKind "CycloneDX SBOM"
    }
    Write-Host (
        "Verified {0} provenance subjects and {1} CycloneDX SBOM subjects." -f
        $provenanceSubjects.Count,
        $publishableExecutables.Count
    )
}

function Assert-RemoteMainCommit {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GhPath,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedRepository,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommit,

        [Parameter(Mandatory = $true)]
        [string]$Description,

        [Parameter(Mandatory = $false)]
        [scriptblock]$GhInvoker
    )

    if ($ExpectedRepository -cne "GrihmLord/DupeZ") {
        throw "Remote-main verification is restricted to GrihmLord/DupeZ."
    }
    $commit = $ExpectedCommit.Trim().ToLowerInvariant()
    if ($commit -cnotmatch '^[0-9a-f]{40}$') {
        throw "Remote-main verification requires an exact commit SHA."
    }

    if ($null -eq $GhInvoker) {
        $ghExecutable = $GhPath
        $GhInvoker = {
            param([string[]]$Arguments)
            $output = @(& $ghExecutable @Arguments 2>$null)
            return [pscustomobject]@{
                ExitCode = $LASTEXITCODE
                Output = $output
            }
        }.GetNewClosure()
    }

    Write-Host "`n=== $Description ==="
    $endpoint = "repos/GrihmLord/DupeZ/git/ref/heads/main"
    $arguments = @(
        "api",
        "--hostname", "github.com",
        "--method", "GET",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
        $endpoint
    )
    $result = & $GhInvoker -Arguments $arguments
    if ($null -eq $result -or [int]$result.ExitCode -ne 0) {
        throw "Could not authenticate the canonical remote main reference."
    }
    $responseText = (@($result.Output) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($responseText)) {
        throw "Canonical remote main returned an empty response."
    }
    try {
        $response = $responseText | ConvertFrom-Json
    }
    catch {
        throw "Canonical remote main returned malformed JSON."
    }
    if ($response -is [System.Array]) {
        throw "Canonical remote main returned an ambiguous response."
    }
    $properties = @($response.PSObject.Properties.Name)
    if ("ref" -notin $properties -or "object" -notin $properties) {
        throw "Canonical remote main response omitted required fields."
    }
    $objectProperties = @($response.object.PSObject.Properties.Name)
    if (
        "type" -notin $objectProperties -or
        "sha" -notin $objectProperties
    ) {
        throw "Canonical remote main object omitted required fields."
    }
    $remoteCommit = ([string]$response.object.sha).Trim().ToLowerInvariant()
    if (
        [string]$response.ref -cne "refs/heads/main" -or
        [string]$response.object.type -cne "commit" -or
        $remoteCommit -cnotmatch '^[0-9a-f]{40}$'
    ) {
        throw "Canonical remote main response failed strict validation."
    }
    if ($remoteCommit -cne $commit) {
        throw "Canonical remote main does not match the staged commit."
    }
}

function New-PrivateStageDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [ValidateSet("hardware-evidence", "release-upload", "release-verify")]
        [string]$Purpose = "hardware-evidence"
    )

    $tempRoot = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    )
    $leaf = "dupez-$Purpose-" + [Guid]::NewGuid().ToString("N")
    $path = [System.IO.Path]::GetFullPath((Join-Path $tempRoot $leaf))
    $tempPrefix = $tempRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $path.StartsWith(
        $tempPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Private stage path escaped the system temporary directory."
    }

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    if ($null -eq $identity.User) {
        throw "Could not resolve the current Windows identity."
    }
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($identity.User)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        (
            [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        ),
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($rule)
    try {
        $directory = [System.IO.Directory]::CreateDirectory($path, $acl)
        if (
            ($directory.Attributes -band
                [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "Private stage directory is a reparse point."
        }
        if (@(Get-ChildItem -LiteralPath $path -Force).Count -ne 0) {
            throw "Private stage directory was not newly created and empty."
        }
        $actualAcl = $directory.GetAccessControl(
            (
                [System.Security.AccessControl.AccessControlSections]::Access -bor
                [System.Security.AccessControl.AccessControlSections]::Owner
            )
        )
        $actualOwner = $actualAcl.GetOwner(
            [System.Security.Principal.SecurityIdentifier]
        )
        $actualRules = @(
            $actualAcl.GetAccessRules(
                $true,
                $true,
                [System.Security.Principal.SecurityIdentifier]
            )
        )
        $unexpectedRules = @(
            $actualRules | Where-Object {
                $_.IdentityReference -ne $identity.User -or
                $_.AccessControlType -ne (
                    [System.Security.AccessControl.AccessControlType]::Allow
                )
            }
        )
        if (
            -not $actualAcl.AreAccessRulesProtected -or
            $actualOwner -ne $identity.User -or
            $actualRules.Count -lt 1 -or
            $unexpectedRules.Count -ne 0
        ) {
            throw "Private stage directory ACL is not owner-exclusive."
        }
    }
    catch {
        $creationError = $_.Exception.Message
        if (Test-Path -LiteralPath $path) {
            try {
                Remove-PrivateStageDirectory -Path $path
            }
            catch {
                throw (
                    "Could not secure private stage directory ($creationError); " +
                    "safe cleanup also failed: $($_.Exception.Message)"
                )
            }
        }
        throw "Could not secure private stage directory: $creationError"
    }
    return $path
}

function Remove-PrivateStageDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $tempRoot = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    )
    $tempPrefix = $tempRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    $leaf = [System.IO.Path]::GetFileName($fullPath)
    if (
        -not $fullPath.StartsWith(
            $tempPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        $leaf -notmatch (
            '^dupez-(hardware-evidence|release-upload|release-verify)-' +
            '[0-9a-f]{32}$'
        )
    ) {
        throw "Refusing to remove an unexpected private stage path: $Path"
    }
    if (-not (Test-Path -LiteralPath $fullPath)) {
        return
    }
    $rootItem = Get-Item -LiteralPath $fullPath -Force
    if (
        -not $rootItem.PSIsContainer -or
        ($rootItem.Attributes -band
            [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Refusing to recurse into a private stage reparse point: $Path"
    }
    $reparseChildren = @(
        Get-ChildItem -LiteralPath $fullPath -Recurse -Force |
            Where-Object {
                ($_.Attributes -band
                    [System.IO.FileAttributes]::ReparsePoint) -ne 0
            }
    )
    if ($reparseChildren.Count -ne 0) {
        throw "Refusing to remove a private stage containing reparse points."
    }
    Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $fullPath) {
        throw "Private stage directory cleanup did not complete: $fullPath"
    }
}

function Invoke-GhArtifactArchiveDownload {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GhPath,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedRepository,

        [Parameter(Mandatory = $true)]
        [int64]$ArtifactId,

        [Parameter(Mandatory = $true)]
        [string]$ArchivePath
    )

    if ($ExpectedRepository -cne "GrihmLord/DupeZ" -or $ArtifactId -lt 1) {
        throw "Artifact-ID download arguments are invalid."
    }
    if (Test-Path -LiteralPath $ArchivePath) {
        throw "Artifact archive destination already exists."
    }
    $endpoint = (
        "repos/$ExpectedRepository/actions/artifacts/$ArtifactId/zip"
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $GhPath
    $startInfo.Arguments = (
        "api --hostname github.com --method GET " +
        "--header Accept:application/vnd.github+json " +
        "--header X-GitHub-Api-Version:2022-11-28 " +
        $endpoint
    )
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $archive = [System.IO.File]::Open(
        $ArchivePath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "GitHub artifact-ID download could not be started."
        }
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $copyTask = $process.StandardOutput.BaseStream.CopyToAsync($archive)
        if (-not $process.WaitForExit(60000)) {
            $process.Kill()
            throw "GitHub artifact-ID download timed out."
        }
        $copyTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $archive.Flush($true)
        if ($process.ExitCode -ne 0) {
            throw (
                "GitHub artifact-ID download failed with exit code " +
                "$($process.ExitCode): $stderr"
            )
        }
    }
    catch {
        $archive.Dispose()
        Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
        throw
    }
    finally {
        $archive.Dispose()
        $process.Dispose()
    }
}

function Expand-HardwareEvidenceArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entries = @($zip.Entries)
        if (
            $entries.Count -ne 1 -or
            $entries[0].FullName -cne "hardware-smoketest-evidence.json" -or
            $entries[0].Name -cne "hardware-smoketest-evidence.json" -or
            $entries[0].Length -lt 1
        ) {
            throw "Downloaded hardware evidence artifact has unexpected contents."
        }
        $destination = Join-Path `
            $DestinationRoot `
            "hardware-smoketest-evidence.json"
        $inputStream = $entries[0].Open()
        try {
            $outputStream = [System.IO.File]::Open(
                $destination,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $inputStream.CopyTo($outputStream)
                $outputStream.Flush($true)
            }
            finally {
                $outputStream.Dispose()
            }
        }
        finally {
            $inputStream.Dispose()
        }
        return $destination
    }
    finally {
        $zip.Dispose()
    }
}

function Assert-AuthenticatedHardwareEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$GhPath,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedRepository,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommit,

        [Parameter(Mandatory = $true)]
        [object]$Evidence,

        [Parameter(Mandatory = $true)]
        [string]$LocalEvidencePath,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [string]$HardwareEvidenceValidatorPath,

        [Parameter(Mandatory = $false)]
        [scriptblock]$GhInvoker,

        [Parameter(Mandatory = $false)]
        [scriptblock]$EvidenceValidator,

        [Parameter(Mandatory = $false)]
        [scriptblock]$ArtifactDownloader
    )

    if ($ExpectedRepository -cne "GrihmLord/DupeZ") {
        throw "Hardware evidence must be authenticated against GrihmLord/DupeZ."
    }
    if (-not (Test-Path -LiteralPath $LocalEvidencePath -PathType Leaf)) {
        throw "Local hardware evidence is missing."
    }
    $commit = $ExpectedCommit.Trim().ToLowerInvariant()
    if ($commit -notmatch '^[0-9a-f]{40}$') {
        throw "Hardware evidence authentication requires a full commit SHA."
    }
    $invocation = $Evidence.invocation
    if ($null -eq $invocation) {
        throw "Hardware evidence has no GitHub invocation binding."
    }
    $runIdText = ([string]$invocation.run_id).Trim()
    $runAttemptText = ([string]$invocation.run_attempt).Trim()
    if ($runIdText -notmatch '^[1-9][0-9]*$') {
        throw "Hardware evidence has an invalid GitHub run_id."
    }
    if ($runAttemptText -notmatch '^[1-9][0-9]*$') {
        throw "Hardware evidence has an invalid GitHub run_attempt."
    }
    [int64]$runId = $runIdText
    [int64]$runAttempt = $runAttemptText

    if ($null -eq $GhInvoker) {
        $ghExecutable = $GhPath
        $GhInvoker = {
            param([string[]]$Arguments)
            $output = @(& $ghExecutable @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
            return [pscustomobject]@{
                ExitCode = $exitCode
                Output = $output
            }
        }.GetNewClosure()
    }
    if ($null -eq $EvidenceValidator) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "Hardware evidence validator Python is missing."
        }
        if (-not (
            Test-Path -LiteralPath $HardwareEvidenceValidatorPath -PathType Leaf
        )) {
            throw "Hardware evidence validator script is missing."
        }
        $validatorPython = $PythonPath
        $validatorScript = $HardwareEvidenceValidatorPath
        $EvidenceValidator = {
            param(
                [string]$EvidencePath,
                [string]$Commit
            )
            Write-Host "`n=== HARDWARE EVIDENCE VALIDATION (AUTHENTICATED DOWNLOAD) ==="
            & $validatorPython `
                -I $validatorScript validate `
                --evidence $EvidencePath `
                --commit $Commit
            if ($LASTEXITCODE -ne 0) {
                throw "Authenticated hardware evidence validation failed."
            }
        }.GetNewClosure()
    }
    if ($null -eq $ArtifactDownloader) {
        $downloadGh = $GhPath
        $ArtifactDownloader = {
            param(
                [int64]$ArtifactId,
                [string]$Repository,
                [string]$ArchivePath
            )
            Invoke-GhArtifactArchiveDownload `
                -GhPath $downloadGh `
                -ExpectedRepository $Repository `
                -ArtifactId $ArtifactId `
                -ArchivePath $ArchivePath
        }.GetNewClosure()
    }
    $invokeCheckedGh = {
        param(
            [string[]]$Arguments,
            [string]$Description
        )
        $result = & $GhInvoker -Arguments $Arguments
        if ($null -eq $result -or [int]$result.ExitCode -ne 0) {
            throw "$Description failed."
        }
        return (@($result.Output) -join [Environment]::NewLine)
    }
    $parseGhJson = {
        param(
            [string[]]$Arguments,
            [string]$Description
        )
        $text = & $invokeCheckedGh `
            -Arguments $Arguments `
            -Description $Description
        try {
            return $text | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "$Description returned invalid JSON."
        }
    }

    $authenticatedUser = & $parseGhJson `
        -Arguments @("api", "--hostname", "github.com", "--method", "GET", "user") `
        -Description "GitHub authentication check"
    if ([string]::IsNullOrWhiteSpace([string]$authenticatedUser.login)) {
        throw "GitHub authentication check returned no account identity."
    }

    $run = & $parseGhJson `
        -Arguments @(
            "api", "--hostname", "github.com", "--method", "GET",
            "repos/$ExpectedRepository/actions/runs/$runId"
        ) `
        -Description "Hardware workflow run lookup"
    $expectedWorkflowPath = ".github/workflows/hardware-smoketest.yml"
    $runWorkflowPath = [string]$run.path
    $workflowRefSeparator = $runWorkflowPath.IndexOf("@")
    if ($workflowRefSeparator -lt 0) {
        $runWorkflowFile = $runWorkflowPath
        $runWorkflowRef = ""
    }
    else {
        $runWorkflowFile = $runWorkflowPath.Substring(0, $workflowRefSeparator)
        $runWorkflowRef = $runWorkflowPath.Substring($workflowRefSeparator + 1)
    }
    [int64]$workflowId = $run.workflow_id
    if (
        [int64]$run.id -ne $runId -or
        [int64]$run.run_attempt -ne $runAttempt -or
        [string]$run.status -cne "completed" -or
        [string]$run.conclusion -cne "success" -or
        ([string]$run.head_sha).ToLowerInvariant() -cne $commit -or
        [string]$run.head_branch -cne "main" -or
        [string]$run.name -cne "Hardware Smoketest" -or
        $runWorkflowFile -cne $expectedWorkflowPath -or
        $runWorkflowRef -cnotin @("", "main", "refs/heads/main") -or
        $workflowId -lt 1 -or
        [string]$run.repository.full_name -cne $ExpectedRepository -or
        [string]$run.event -cnotin @("schedule", "workflow_dispatch")
    ) {
        throw "Hardware workflow run metadata does not match release policy."
    }
    $workflow = & $parseGhJson `
        -Arguments @(
            "api", "--hostname", "github.com", "--method", "GET",
            "repos/$ExpectedRepository/actions/workflows/$workflowId"
        ) `
        -Description "Hardware workflow identity lookup"
    if (
        [int64]$workflow.id -ne $workflowId -or
        [string]$workflow.name -cne "Hardware Smoketest" -or
        [string]$workflow.path -cne $expectedWorkflowPath
    ) {
        throw "Hardware workflow identity does not match release policy."
    }

    $artifactName = "hardware-smoketest-evidence-$commit"
    $artifactPayload = & $parseGhJson `
        -Arguments @(
            "api", "--hostname", "github.com", "--method", "GET",
            "repos/$ExpectedRepository/actions/runs/$runId/artifacts?per_page=100"
        ) `
        -Description "Hardware evidence artifact lookup"
    $allArtifacts = @($artifactPayload.artifacts)
    if ([int]$artifactPayload.total_count -ne $allArtifacts.Count) {
        throw "Hardware evidence artifact listing is incomplete or ambiguous."
    }
    $matchingArtifacts = @(
        $allArtifacts | Where-Object { [string]$_.name -ceq $artifactName }
    )
    if ($matchingArtifacts.Count -ne 1) {
        throw (
            "Expected exactly one authenticated hardware evidence artifact; " +
            "found $($matchingArtifacts.Count)."
        )
    }
    $artifact = $matchingArtifacts[0]
    $artifactDigest = ([string]$artifact.digest).Trim().ToLowerInvariant()
    if (
        [int64]$artifact.id -lt 1 -or
        [int64]$artifact.size_in_bytes -lt 1 -or
        $artifact.expired -ne $false -or
        [int64]$artifact.workflow_run.id -ne $runId -or
        $artifactDigest -notmatch '^sha256:[0-9a-f]{64}$'
    ) {
        throw "Hardware evidence artifact metadata is invalid or expired."
    }
    [int64]$artifactId = $artifact.id
    $expectedArchiveHash = $artifactDigest.Substring(7)

    $tempRoot = $null
    try {
        $tempRoot = New-PrivateStageDirectory -Purpose "hardware-evidence"
        $archivePath = Join-Path $tempRoot "artifact-$artifactId.zip"
        & $ArtifactDownloader `
            -ArtifactId $artifactId `
            -Repository $ExpectedRepository `
            -ArchivePath $archivePath
        $archiveItem = Assert-RegularFile `
            -Path $archivePath `
            -Description "Authenticated hardware evidence archive"
        if ($archiveItem.Length -lt 1) {
            throw "Authenticated hardware evidence archive is empty."
        }
        $archiveHash = Get-Sha256 -Path $archiveItem.FullName
        if ($archiveHash -cne $expectedArchiveHash) {
            throw "Authenticated hardware evidence archive digest mismatch."
        }
        $downloadedPath = Expand-HardwareEvidenceArchive `
            -ArchivePath $archiveItem.FullName `
            -DestinationRoot $tempRoot
        $localItem = Assert-RegularFile `
            -Path $LocalEvidencePath `
            -Description "Local hardware evidence"
        $downloadedItem = Assert-RegularFile `
            -Path $downloadedPath `
            -Description "Authenticated hardware evidence"
        $localHash = Get-Sha256 -Path $localItem.FullName
        $downloadedHash = Get-Sha256 -Path $downloadedItem.FullName
        if (
            [int64]$localItem.Length -ne [int64]$downloadedItem.Length -or
            $localHash -cne $downloadedHash
        ) {
            throw (
                "Local hardware evidence does not exactly match the " +
                "authenticated GitHub Actions artifact."
            )
        }
        & $EvidenceValidator `
            -EvidencePath $downloadedItem.FullName `
            -Commit $commit | Out-Null
        try {
            $trustedEvidence = [System.IO.File]::ReadAllText(
                $downloadedItem.FullName,
                [System.Text.Encoding]::UTF8
            ) | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "Authenticated hardware evidence is not valid JSON."
        }
        if (
            [string]$trustedEvidence.invocation.run_id -cne $runIdText -or
            [string]$trustedEvidence.invocation.run_attempt -cne $runAttemptText
        ) {
            throw "Authenticated evidence does not bind its workflow run identity."
        }
        return [pscustomobject]@{
            Attestation = [ordered]@{
                run_id = $runId
                run_attempt = $runAttempt
                artifact_id = $artifactId
                artifact_name = $artifactName
                artifact_archive_sha256 = $archiveHash
                evidence_sha256 = $downloadedHash
            }
            Evidence = $trustedEvidence
        }
    }
    finally {
        if ($null -ne $tempRoot -and (Test-Path -LiteralPath $tempRoot)) {
            Remove-PrivateStageDirectory -Path $tempRoot
        }
    }
}

$gh = (Get-Command gh -ErrorAction Stop).Source
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Repository Python was not found at .venv\Scripts\python.exe."
}

$sourceIdentity = Get-ReleaseGitIdentity `
    -RepositoryRoot $repoRoot `
    -RequiredBranch "main"
$commit = $sourceIdentity.Commit
if (
    [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN) -and
    [string]::IsNullOrWhiteSpace($env:GH_TOKEN)
) {
    throw "GITHUB_TOKEN or GH_TOKEN is required."
}
if ($Repository -cne "GrihmLord/DupeZ") {
    throw "Release staging is restricted to GrihmLord/DupeZ."
}
$attestationSignerWorkflow = if ($AllowUnsigned) {
    "$Repository/.github/workflows/unsigned-public-release.yml"
}
else {
    "$Repository/.github/workflows/release.yml"
}

$releaseSnapshotRoot = $null
$releaseAssetLocks = @()
$releaseNotesLock = $null
try {
    $baseAssetNames = @(
        "DupeZ-GPU.exe",
        "DupeZ-Compat.exe",
        "DupeZ_v${Version}_Setup.exe",
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
        "DupeZ-v${Version}-source.zip",
        "SHA256SUMS.txt",
        "release-attestation.json",
        "DefenderScan.txt"
    )
    $preflightInputAssets = @(
        foreach ($name in $baseAssetNames) {
            Assert-RegularFile `
                -Path (Join-Path $distRoot $name) `
                -Description "Preflight release asset"
        }
    )
$preflightInputLocks = @()
try {
    $preflightInputLocks = @(
        Open-ReleaseAssetReadLocks -Assets $preflightInputAssets
    )
    $preflightInputBinding = Get-ReleaseAssetBinding `
        -Assets $preflightInputAssets
    $preflightArguments = @(
        "-I", "scripts\release_preflight.py",
        "--version", $Version,
        "--dist"
    )
    if ($AllowUnsigned) {
        $preflightArguments += "--allow-unsigned"
    }
    Invoke-Checked `
        -FilePath $pythonPath `
        -Description "FINAL DIST RELEASE PREFLIGHT" `
        -ArgumentList $preflightArguments

$releaseSnapshotRoot = New-PrivateStageDirectory -Purpose "release-upload"
$assets = @(
    Copy-ReleaseAssetSnapshot `
        -SourceRoot $distRoot `
        -DestinationRoot $releaseSnapshotRoot `
        -Names $baseAssetNames
)
Assert-ReleaseAssetBinding `
    -Assets $assets `
    -Hashes $preflightInputBinding.Hashes `
    -Lengths $preflightInputBinding.Lengths `
    -Description "Release snapshot after preflight"
}
finally {
    foreach ($lock in $preflightInputLocks) {
        $lock.Dispose()
    }
}

$gpuPath = Join-Path $releaseSnapshotRoot "DupeZ-GPU.exe"
$compatPath = Join-Path $releaseSnapshotRoot "DupeZ-Compat.exe"
$installerPath = Join-Path $releaseSnapshotRoot "DupeZ_v${Version}_Setup.exe"
$gpuHash = Get-Sha256 -Path $gpuPath
$compatHash = Get-Sha256 -Path $compatPath
$installerHash = Get-Sha256 -Path $installerPath
$expectedSigningMode = if ($AllowUnsigned) { "unsigned" } else { "authenticode" }

$releaseAttestation = Read-JsonFile `
    -Path (Join-Path $releaseSnapshotRoot "release-attestation.json") `
    -Description "release attestation"
$gpuEvidence = Read-JsonFile `
    -Path (Join-Path $distRoot "frozen-runtime-evidence-gpu.json") `
    -Description "GPU frozen runtime evidence"
$compatEvidence = Read-JsonFile `
    -Path (Join-Path $distRoot "frozen-runtime-evidence-compat.json") `
    -Description "Compat frozen runtime evidence"
$manualEvidence = Read-JsonFile `
    -Path (Join-Path $distRoot "manual-release-validation.json") `
    -Description "manual release validation"
$hardwareEvidencePath = Join-Path $distRoot "hardware-smoketest-evidence.json"
$localHardwareEvidence = Read-JsonFile `
    -Path $hardwareEvidencePath `
    -Description "hardware-smoketest evidence"
$authenticatedHardwareEvidenceResult = Assert-AuthenticatedHardwareEvidence `
    -GhPath $gh `
    -ExpectedRepository "GrihmLord/DupeZ" `
    -ExpectedCommit $commit `
    -Evidence $localHardwareEvidence `
    -LocalEvidencePath $hardwareEvidencePath `
    -PythonPath $pythonPath `
    -HardwareEvidenceValidatorPath (
        Join-Path $repoRoot "scripts\hardware_evidence.py"
    )
$hardwareEvidence = $authenticatedHardwareEvidenceResult.Evidence
$authenticatedHardwareEvidence = `
    $authenticatedHardwareEvidenceResult.Attestation

if ($releaseAttestation.schema -ne "dupez.release-attestation.v1") {
    throw "Release attestation schema mismatch."
}
if (
    $releaseAttestation.version -ne $Version -or
    $releaseAttestation.commit -ne $commit
) {
    throw "Release attestation version/commit mismatch."
}
if ($releaseAttestation.distribution_signing_mode -ne $expectedSigningMode) {
    throw (
        "Release attestation signing mode mismatch: expected " +
        "$expectedSigningMode, found " +
        "$($releaseAttestation.distribution_signing_mode)."
    )
}
if (
    $Version -eq "5.8.0" -and
    $releaseAttestation.updater_manifest.verified_key_fingerprint -ne
        "5555f0e8c31a40ed" # pragma: allowlist secret
) {
    throw (
        "Release attestation does not bind the required v5.8 recovery " +
        "update signer."
    )
}

Assert-FrozenRuntimeEvidenceContract `
    -Evidence $gpuEvidence `
    -ExpectedVariant "GPU" `
    -ExpectedExecutable "DupeZ-GPU.exe" `
    -ExpectedHash $gpuHash `
    -ExpectedCommit $commit
Assert-FrozenRuntimeEvidenceContract `
    -Evidence $compatEvidence `
    -ExpectedVariant "Compat" `
    -ExpectedExecutable "DupeZ-Compat.exe" `
    -ExpectedHash $compatHash `
    -ExpectedCommit $commit

if ($manualEvidence.schema -ne "dupez.manual-release-validation.v1") {
    throw "Manual release validation schema mismatch."
}
if ($manualEvidence.version -ne $Version -or $manualEvidence.commit -ne $commit) {
    throw "Manual release validation version/commit mismatch."
}
if ($manualEvidence.distribution_signing_mode -ne $expectedSigningMode) {
    throw (
        "Manual release validation signing mode mismatch: expected " +
        "$expectedSigningMode, found " +
        "$($manualEvidence.distribution_signing_mode)."
    )
}
if (
    $manualEvidence.artifacts.gpu_sha256 -ne $gpuHash -or
    $manualEvidence.artifacts.compat_sha256 -ne $compatHash -or
    $manualEvidence.artifacts.installer_sha256 -ne $installerHash
) {
    throw "Manual release validation artifact hash mismatch."
}
$manualNativeBinding = $manualEvidence.hardware_evidence.source_native_artifacts |
    ConvertTo-Json -Depth 8 -Compress
$hardwareNativeBinding = $hardwareEvidence.source_native_artifacts |
    ConvertTo-Json -Depth 8 -Compress
if (
    $manualEvidence.hardware_evidence.schema -ne $hardwareEvidence.schema -or
    $manualEvidence.hardware_evidence.commit -ne $hardwareEvidence.commit -or
    [int]$manualEvidence.hardware_evidence.test_count -ne
        [int]$hardwareEvidence.tests.count -or
    $manualNativeBinding -ne $hardwareNativeBinding
) {
    throw "Manual release validation hardware evidence binding mismatch."
}
$manualGates = @(
    Assert-ExactManualReleaseGates `
        -Gates $manualEvidence.gates `
        -RecorderPath (Join-Path $PSScriptRoot "record_manual_release_validation.ps1")
)

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
    hardware_smoketest = [ordered]@{
        schema = $hardwareEvidence.schema
        commit = $hardwareEvidence.commit
        authenticated_github_actions = $authenticatedHardwareEvidence
        tests = [ordered]@{
            result = $hardwareEvidence.tests.result
            count = [int]$hardwareEvidence.tests.count
        }
        source_native_artifacts = @($hardwareEvidence.source_native_artifacts)
        limitation = (
            "Source-run hardware evidence binds the exact commit and " +
            "provenance hashes; frozen executable hashes are validated " +
            "separately by frozen-runtime evidence."
        )
    }
    manual_validation = [ordered]@{
        recorded_at_utc = $manualEvidence.recorded_at_utc
        completed_gates = @($manualGates | ForEach-Object { $_.Name } | Sort-Object)
    }
}
$publicValidationPath = Join-Path `
    $releaseSnapshotRoot `
    "release-validation-attestation.json"
$publicValidation | ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath $publicValidationPath -Encoding UTF8

$assetNames = @($baseAssetNames) + "release-validation-attestation.json"
$assets = @(
    foreach ($name in $assetNames) {
        $path = Join-Path $releaseSnapshotRoot $name
        $item = Assert-RegularFile `
            -Path $path `
            -Description "Required snapshotted release asset"
        if ($item.Length -le 0) {
            throw "Required snapshotted release asset is empty: $name"
        }
        $item
    }
)
$snapshotEntries = @(
    Get-ChildItem -LiteralPath $releaseSnapshotRoot -Force
)
if (
    $snapshotEntries.Count -ne $assets.Count -or
    @($snapshotEntries | Where-Object { $_.PSIsContainer }).Count -ne 0
) {
    throw "Release asset snapshot inventory is not exact."
}

# Verify the finalizer's primary hashes before adding the sanitized validation
# attestation hash. Raw host/manual evidence remains private and is not uploaded.
$sumPath = Join-Path $releaseSnapshotRoot "SHA256SUMS.txt"
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

# Bind the private snapshot exactly once. Every subsequent local and remote
# comparison uses these captured values rather than mutable files under dist/.
$assets = @(
    foreach ($name in $assetNames) {
        Assert-RegularFile `
            -Path (Join-Path $releaseSnapshotRoot $name) `
            -Description "Final snapshotted release asset"
    }
)
$snapshotBinding = Get-ReleaseAssetBinding -Assets $assets
$snapshotHashes = $snapshotBinding.Hashes
$snapshotLengths = $snapshotBinding.Lengths
$releaseAssetLocks = @(
    Open-ReleaseAssetReadLocks -Assets $assets
)
Assert-ReleaseAssetBinding `
    -Assets $assets `
    -Hashes $snapshotHashes `
    -Lengths $snapshotLengths `
    -Description "Locked release snapshot"

$tag = "v$Version"
$notes = Join-Path $repoRoot "docs\release-notes\v$Version.md"
$notesSource = Assert-RegularFile `
    -Path $notes `
    -Description "Release notes"
if ($notesSource.Length -le 0 -or $notesSource.Length -gt 1048576) {
    throw "Release notes must be non-empty and no larger than 1 MiB."
}
$notesBody = Get-Content -LiteralPath $notesSource.FullName -Raw
if (
    [string]::IsNullOrWhiteSpace($notesBody) -or
    $notesBody.Contains([char]0)
) {
    throw "Release notes are empty or contain invalid data."
}
$releaseTitle = if ($AllowUnsigned) {
    "DupeZ v$Version (UNSIGNED WINDOWS BUILD)"
}
else {
    "DupeZ v$Version"
}
$releaseNotesBanner = if ($AllowUnsigned) {
    (
        "> **Distribution signing: UNSIGNED WINDOWS BUILD.** " +
        "These executables do not carry Authenticode publisher signatures; " +
        "Windows publisher or SmartScreen warnings are expected. Verify the " +
        "published SHA-256 checksums before running them."
    )
}
else {
    (
        "> **Distribution signing: AUTHENTICODE-SIGNED WINDOWS BUILD.** " +
        "Verify the publisher signature and published SHA-256 checksums " +
        "before running the executables."
    )
}
$releaseNotesSnapshotPath = Join-Path `
    $releaseSnapshotRoot `
    "_public-release-notes.md"
[System.IO.File]::WriteAllText(
    $releaseNotesSnapshotPath,
    ($releaseNotesBanner + "`r`n`r`n" + $notesBody),
    (New-Object System.Text.UTF8Encoding($false))
)
$releaseNotesSnapshot = Assert-RegularFile `
    -Path $releaseNotesSnapshotPath `
    -Description "Snapshotted public release notes"
$releaseNotesLock = [System.IO.File]::Open(
    $releaseNotesSnapshot.FullName,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::Read
)

Assert-ReleaseGitIdentityUnchanged `
    -RepositoryRoot $repoRoot `
    -ExpectedCommit $commit `
    -RequiredBranch "main" | Out-Null

# A local tag may exist before the release record. It must already resolve to
# this exact commit; a stale tag is never moved implicitly. An absent tag is the
# normal first-draft case and must remain an empty string rather than a null
# method call under StrictMode.
$tagCommitOutput = @(
    Invoke-TrustedReleaseGit `
        -RepositoryRoot $repoRoot `
        -Arguments @(
            "rev-parse",
            "-q",
            "--verify",
            "refs/tags/$tag^{commit}"
        ) `
        -AllowedExitCodes @(0, 1)
)
$tagCommit = if ($tagCommitOutput.Count -gt 0) {
    ([string]$tagCommitOutput[0]).Trim()
}
else {
    ""
}
if ($tagCommit -and $tagCommit -ne $commit) {
    throw "Existing tag $tag points to $tagCommit instead of $commit."
}

Assert-GitHubArtifactAttestations `
    -GhPath $gh `
    -Assets $assets `
    -Repository $Repository `
    -SignerWorkflow $attestationSignerWorkflow `
    -SourceCommit $commit `
    -Description "VERIFY LOCAL RELEASE SUBJECT ATTESTATIONS BEFORE DRAFT"

Assert-ReleaseGitIdentityUnchanged `
    -RepositoryRoot $repoRoot `
    -ExpectedCommit $commit `
    -RequiredBranch "main" | Out-Null
$releaseJson = & $gh release view $tag --repo $Repository --json isDraft,tagName,targetCommitish 2>$null
$releaseExists = $LASTEXITCODE -eq 0
if ($releaseExists) {
    $release = $releaseJson | ConvertFrom-Json
    if (-not $release.isDraft) {
        throw "Release $tag is already published; immutable assets will not be replaced."
    }
    if ($release.targetCommitish -ne $commit) {
        throw (
            "Existing draft $tag targets $($release.targetCommitish) instead of " +
            "$commit. Delete/recreate the stale draft explicitly."
        )
    }
    $draftMutationDescription = "UPDATE DRAFT RELEASE SIGNING LABEL"
    $draftMutationArguments = @(
        "release", "edit", $tag,
        "--repo", $Repository,
        "--title", $releaseTitle,
        "--notes-file", $releaseNotesSnapshot.FullName
    )
}
else {
    $draftMutationDescription = "CREATE DRAFT RELEASE"
    $draftMutationArguments = @(
        "release", "create", $tag,
        "--repo", $Repository,
        "--draft",
        "--target", $commit,
        "--title", $releaseTitle,
        "--notes-file", $releaseNotesSnapshot.FullName
    )
}
Assert-RemoteMainCommit `
    -GhPath $gh `
    -ExpectedRepository $Repository `
    -ExpectedCommit $commit `
    -Description "VERIFY CANONICAL REMOTE MAIN BEFORE DRAFT"
Invoke-Checked `
    -FilePath $gh `
    -Description $draftMutationDescription `
    -ArgumentList $draftMutationArguments

$uploadArguments = @("release", "upload", $tag, "--repo", $Repository, "--clobber")
$uploadArguments += @($assets | ForEach-Object { $_.FullName })
Assert-ReleaseAssetBinding `
    -Assets $assets `
    -Hashes $snapshotHashes `
    -Lengths $snapshotLengths `
    -Description "Release snapshot before upload"
Assert-ReleaseGitIdentityUnchanged `
    -RepositoryRoot $repoRoot `
    -ExpectedCommit $commit `
    -RequiredBranch "main" | Out-Null
Assert-RemoteMainCommit `
    -GhPath $gh `
    -ExpectedRepository $Repository `
    -ExpectedCommit $commit `
    -Description "VERIFY CANONICAL REMOTE MAIN BEFORE UPLOAD"
Invoke-Checked -FilePath $gh -Description "UPLOAD VERIFIED RELEASE ASSETS" -ArgumentList $uploadArguments
Assert-ReleaseAssetBinding `
    -Assets $assets `
    -Hashes $snapshotHashes `
    -Lengths $snapshotLengths `
    -Description "Release snapshot after upload"

# Read back the draft and bind GitHub's stored asset metadata to the exact local
# set before publication. Source archives generated by GitHub are not part of
# this assets array and do not affect the comparison.
$verifiedJson = & $gh release view $tag --repo $Repository --json isDraft,targetCommitish,name,body,assets
if ($LASTEXITCODE -ne 0) {
    throw "Could not read back the staged release."
}
$verified = $verifiedJson | ConvertFrom-Json
if (-not $verified.isDraft) {
    throw "Release $tag was not a draft after asset upload."
}
if ($verified.targetCommitish -ne $commit) {
    throw "Staged release target changed after upload."
}
if (
    [string]$verified.name -cne $releaseTitle -or
    -not ([string]$verified.body).StartsWith(
        $releaseNotesBanner,
        [StringComparison]::Ordinal
    )
) {
    throw "Staged release signing-mode title or notice is incorrect."
}
$remoteAssets = @($verified.assets)
$expectedNames = @($assets | ForEach-Object { $_.Name })
if ($remoteAssets.Count -ne $assets.Count) {
    throw (
        "Staged release asset count mismatch: expected=$($assets.Count), " +
        "remote=$($remoteAssets.Count)."
    )
}
$unexpectedAssets = @(
    $remoteAssets | Where-Object { $_.name -notin $expectedNames }
)
if ($unexpectedAssets.Count -gt 0) {
    throw (
        "Staged release contains unexpected assets: " +
        (($unexpectedAssets | ForEach-Object { $_.name }) -join ", ")
    )
}
foreach ($asset in $assets) {
    $remote = @(
        $remoteAssets | Where-Object { $_.name -eq $asset.Name }
    )
    if ($remote.Count -ne 1) {
        throw "Staged release does not contain exactly one $($asset.Name) asset."
    }
    if ([int64]$remote[0].size -ne $snapshotLengths[$asset.Name]) {
        throw (
            "Staged release size mismatch for $($asset.Name): local=" +
            "$($snapshotLengths[$asset.Name]), remote=$($remote[0].size)"
        )
    }
}

$downloadRoot = New-PrivateStageDirectory -Purpose "release-verify"
$downloadedAssetLocks = @()
try {
    Invoke-Checked `
        -FilePath $gh `
        -Description "DOWNLOAD STAGED RELEASE FOR HASH VERIFICATION" `
        -ArgumentList @(
            "release", "download", $tag,
            "--repo", $Repository,
            "--dir", $downloadRoot
        )

    $downloadedAssets = @(Get-ChildItem -LiteralPath $downloadRoot -Force)
    if (
        $downloadedAssets.Count -ne $assets.Count -or
        @($downloadedAssets | Where-Object { $_.PSIsContainer }).Count -ne 0
    ) {
        throw (
            "Downloaded release asset count mismatch: expected=" +
            "$($assets.Count), downloaded=$($downloadedAssets.Count)."
        )
    }
    $downloadedAssetLocks = @(
        Open-ReleaseAssetReadLocks -Assets $downloadedAssets
    )
    Assert-ReleaseAssetBinding `
        -Assets $downloadedAssets `
        -Hashes $snapshotHashes `
        -Lengths $snapshotLengths `
        -Description "Downloaded release"
    Assert-GitHubArtifactAttestations `
        -GhPath $gh `
        -Assets $downloadedAssets `
        -Repository $Repository `
        -SignerWorkflow $attestationSignerWorkflow `
        -SourceCommit $commit `
        -Description "VERIFY DOWNLOADED RELEASE SUBJECT ATTESTATIONS AFTER UPLOAD"

    if ($Mode -eq "Publish") {
        Assert-ReleaseAssetBinding `
            -Assets $downloadedAssets `
            -Hashes $snapshotHashes `
            -Lengths $snapshotLengths `
            -Description "Downloaded release immediately before publish"
        Assert-GitHubArtifactAttestations `
            -GhPath $gh `
            -Assets $downloadedAssets `
            -Repository $Repository `
            -SignerWorkflow $attestationSignerWorkflow `
            -SourceCommit $commit `
            -Description "FINAL RELEASE SUBJECT ATTESTATIONS BEFORE PUBLISH"
        Assert-RemoteMainCommit `
            -GhPath $gh `
            -ExpectedRepository $Repository `
            -ExpectedCommit $commit `
            -Description "VERIFY CANONICAL REMOTE MAIN BEFORE PUBLISH"
        Invoke-Checked `
            -FilePath $gh `
            -Description "PUBLISH VERIFIED RELEASE" `
            -ArgumentList @(
                "release", "edit", $tag,
                "--repo", $Repository,
                "--draft=false",
                "--latest"
            )
    }
}
finally {
    foreach ($lock in $downloadedAssetLocks) {
        $lock.Dispose()
    }
    if (Test-Path -LiteralPath $downloadRoot) {
        Remove-PrivateStageDirectory -Path $downloadRoot
    }
}

}
finally {
    foreach ($lock in $releaseAssetLocks) {
        $lock.Dispose()
    }
    $releaseAssetLocks = @()
    if (
        $null -ne $releaseSnapshotRoot -and
        (Test-Path -LiteralPath $releaseSnapshotRoot)
    ) {
        Remove-PrivateStageDirectory -Path $releaseSnapshotRoot
    }
}

Write-Host "`nRELEASE STAGING: PASS" -ForegroundColor Green
Write-Host "Tag: $tag"
Write-Host "Commit: $commit"
Write-Host "Mode: $Mode"
Write-Host "Assets: $($assets.Count)"
