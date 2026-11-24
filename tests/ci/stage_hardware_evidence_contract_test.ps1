#requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stagePath = Join-Path $repoRoot "scripts\stage_release.ps1"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $stagePath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "stage_release.ps1 has PowerShell parse errors."
}

foreach ($functionName in @(
    "Get-Sha256",
    "Assert-RegularFile",
    "Copy-ReleaseAssetSnapshot",
    "Get-ReleaseAssetBinding",
    "Assert-ReleaseAssetBinding",
    "Open-ReleaseAssetReadLocks",
    "Assert-RemoteMainCommit",
    "New-PrivateStageDirectory",
    "Remove-PrivateStageDirectory",
    "Expand-HardwareEvidenceArchive",
    "Assert-AuthenticatedHardwareEvidence"
)) {
    $definitions = @(
        $ast.FindAll(
            {
                param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
            },
            $true
        ) | Where-Object { $_.Name -ceq $functionName }
    )
    if ($definitions.Count -ne 1) {
        throw "Expected exactly one $functionName function in stage_release.ps1."
    }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}

$expectedRepository = "GrihmLord/DupeZ"
$commit = "a" * 40
$runId = 12345
$runAttempt = 2
$workflowId = 9876
$artifactId = 701
$artifactName = "hardware-smoketest-evidence-$commit"
$fixturePayload = [ordered]@{
    schema = "dupez.hardware-smoketest.v1"
    invocation = [ordered]@{
        run_id = [string]$runId
        run_attempt = [string]$runAttempt
    }
}
$fixtureBytes = [Text.Encoding]::UTF8.GetBytes(
    ($fixturePayload | ConvertTo-Json -Depth 4 -Compress)
)

function New-RemoteMainInvoker {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Payload,

        [Parameter(Mandatory = $false)]
        [int]$ExitCode = 0
    )

    return {
        param([string[]]$Arguments)
        $expectedArguments = @(
            "api",
            "--hostname", "github.com",
            "--method", "GET",
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2026-03-10",
            "repos/GrihmLord/DupeZ/git/ref/heads/main"
        )
        if (($Arguments -join "`n") -cne ($expectedArguments -join "`n")) {
            throw "Remote-main verification used an unexpected GitHub request."
        }
        $output = if ($Payload -is [string]) {
            @($Payload)
        }
        else {
            @($Payload | ConvertTo-Json -Depth 6 -Compress)
        }
        return [pscustomobject]@{
            ExitCode = $ExitCode
            Output = $output
        }
    }.GetNewClosure()
}

$validRemoteMain = [ordered]@{
    ref = "refs/heads/main"
    object = [ordered]@{
        type = "commit"
        sha = $commit
    }
}
Assert-RemoteMainCommit `
    -GhPath "gh.exe" `
    -ExpectedRepository $expectedRepository `
    -ExpectedCommit $commit `
    -Description "fixture remote main" `
    -GhInvoker (New-RemoteMainInvoker -Payload $validRemoteMain)

function Assert-RemoteMainRejected {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Payload,

        [Parameter(Mandatory = $false)]
        [int]$ExitCode = 0
    )

    $rejected = $false
    try {
        Assert-RemoteMainCommit `
            -GhPath "gh.exe" `
            -ExpectedRepository $expectedRepository `
            -ExpectedCommit $commit `
            -Description "invalid fixture remote main" `
            -GhInvoker (
                New-RemoteMainInvoker -Payload $Payload -ExitCode $ExitCode
            )
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw "Remote-main verification accepted an invalid response."
    }
}

Assert-RemoteMainRejected -Payload ([ordered]@{
    ref = "refs/heads/other"
    object = [ordered]@{ type = "commit"; sha = $commit }
})
Assert-RemoteMainRejected -Payload ([ordered]@{
    ref = "refs/heads/main"
    object = [ordered]@{ type = "tag"; sha = $commit }
})
Assert-RemoteMainRejected -Payload ([ordered]@{
    ref = "refs/heads/main"
    object = [ordered]@{ type = "commit"; sha = ("b" * 40) }
})
Assert-RemoteMainRejected -Payload '[{"ref":"refs/heads/main"}]'
Assert-RemoteMainRejected -Payload '{malformed'
Assert-RemoteMainRejected -Payload $validRemoteMain -ExitCode 1

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function New-FixtureArchiveBytes {
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$EvidenceBytes,

        [Parameter(Mandatory = $false)]
        [switch]$IncludeUnexpectedEntry
    )

    $memory = New-Object System.IO.MemoryStream
    $zip = [System.IO.Compression.ZipArchive]::new(
        $memory,
        [System.IO.Compression.ZipArchiveMode]::Create,
        $true
    )
    try {
        $entry = $zip.CreateEntry(
            "hardware-smoketest-evidence.json",
            [System.IO.Compression.CompressionLevel]::NoCompression
        )
        $entry.LastWriteTime = [DateTimeOffset]::Parse("2026-08-14T00:00:00Z")
        $stream = $entry.Open()
        try {
            $stream.Write($EvidenceBytes, 0, $EvidenceBytes.Length)
        }
        finally {
            $stream.Dispose()
        }
        if ($IncludeUnexpectedEntry) {
            $extra = $zip.CreateEntry(
                "unexpected.txt",
                [System.IO.Compression.CompressionLevel]::NoCompression
            )
            $extra.LastWriteTime = [DateTimeOffset]::Parse(
                "2026-08-14T00:00:00Z"
            )
            $extraStream = $extra.Open()
            try {
                $extraStream.WriteByte(1)
            }
            finally {
                $extraStream.Dispose()
            }
        }
    }
    finally {
        $zip.Dispose()
    }
    $bytes = $memory.ToArray()
    $memory.Dispose()
    return $bytes
}

function Get-BytesSha256 {
    param([byte[]]$Bytes)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString(
            $sha256.ComputeHash($Bytes)
        ).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

$fixtureArchiveBytes = New-FixtureArchiveBytes -EvidenceBytes $fixtureBytes
$fixtureArchiveSha256 = Get-BytesSha256 -Bytes $fixtureArchiveBytes

function New-TestState {
    return [pscustomobject]@{
        Event = "schedule"
        HeadSha = $commit
        Status = "completed"
        Conclusion = "success"
        WorkflowName = "Hardware Smoketest"
        WorkflowPath = ".github/workflows/hardware-smoketest.yml"
        MatchingArtifactCount = 1
        TotalCountDelta = 0
        ArtifactId = $artifactId
        ArtifactDigest = "sha256:$fixtureArchiveSha256"
        DownloadBytes = $fixtureArchiveBytes
        LastDownloadDirectory = $null
        DownloadInvocations = 0
        DownloadedArtifactId = $null
        PrivateAclProtected = $false
        PrivateAclOnlyCurrentUser = $false
        ValidatorInvocations = 0
        ValidatedEvidencePath = $null
    }
}

function New-MockEvidenceValidator {
    param(
        [Parameter(Mandatory = $true)]
        [object]$State
    )

    return {
        param(
            [string]$EvidencePath,
            [string]$Commit
        )
        if (
            $Commit -cne $commit -or
            $EvidencePath -cne (
                Join-Path `
                    $State.LastDownloadDirectory `
                    "hardware-smoketest-evidence.json"
            )
        ) {
            throw "Validator did not receive the authenticated downloaded copy."
        }
        $State.ValidatorInvocations++
        $State.ValidatedEvidencePath = $EvidencePath
    }.GetNewClosure()
}

function New-MockArtifactDownloader {
    param(
        [Parameter(Mandatory = $true)]
        [object]$State
    )

    return {
        param(
            [int64]$ArtifactId,
            [string]$Repository,
            [string]$ArchivePath
        )
        if (
            $ArtifactId -ne [int64]$State.ArtifactId -or
            $Repository -cne $expectedRepository -or
            [IO.Path]::GetFileName($ArchivePath) -cne
                "artifact-$($State.ArtifactId).zip"
        ) {
            throw "Artifact downloader did not receive the listed artifact ID."
        }
        $State.LastDownloadDirectory = Split-Path -Parent $ArchivePath
        $State.DownloadInvocations++
        $State.DownloadedArtifactId = $ArtifactId

        $directory = Get-Item -LiteralPath $State.LastDownloadDirectory -Force
        $acl = $directory.GetAccessControl(
            [System.Security.AccessControl.AccessControlSections]::Access
        )
        $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        $rules = @(
            $acl.GetAccessRules(
                $true,
                $true,
                [System.Security.Principal.SecurityIdentifier]
            )
        )
        $State.PrivateAclProtected = $acl.AreAccessRulesProtected
        $State.PrivateAclOnlyCurrentUser = (
            $rules.Count -ge 1 -and
            @(
                $rules | Where-Object {
                    $_.IdentityReference -ne $currentSid
                }
            ).Count -eq 0
        )
        [IO.File]::WriteAllBytes($ArchivePath, [byte[]]$State.DownloadBytes)
    }.GetNewClosure()
}

function New-MockGhInvoker {
    param(
        [Parameter(Mandatory = $true)]
        [object]$State
    )

    return {
        param([string[]]$Arguments)

        $endpoint = $Arguments[$Arguments.Count - 1]
        if ($Arguments[0] -ceq "api" -and $endpoint -ceq "user") {
            $payload = [ordered]@{ login = "release-bot" }
        }
        elseif (
            $Arguments[0] -ceq "api" -and
            $endpoint -ceq "repos/$expectedRepository/actions/runs/$runId"
        ) {
            $payload = [ordered]@{
                id = $runId
                run_attempt = $runAttempt
                status = $State.Status
                conclusion = $State.Conclusion
                head_sha = $State.HeadSha
                head_branch = "main"
                name = "Hardware Smoketest"
                path = ".github/workflows/hardware-smoketest.yml@main"
                workflow_id = $workflowId
                repository = [ordered]@{ full_name = $expectedRepository }
                event = $State.Event
            }
        }
        elseif (
            $Arguments[0] -ceq "api" -and
            $endpoint -ceq (
                "repos/$expectedRepository/actions/workflows/$workflowId"
            )
        ) {
            $payload = [ordered]@{
                id = $workflowId
                name = $State.WorkflowName
                path = $State.WorkflowPath
            }
        }
        elseif (
            $Arguments[0] -ceq "api" -and
            $endpoint -ceq (
                "repos/$expectedRepository/actions/runs/$runId/" +
                "artifacts?per_page=100"
            )
        ) {
            $artifacts = @()
            foreach ($number in 1..([int]$State.MatchingArtifactCount)) {
                if ([int]$State.MatchingArtifactCount -eq 0) { break }
                $artifacts += [ordered]@{
                    id = [int64]$State.ArtifactId + $number - 1
                    name = $artifactName
                    size_in_bytes = $fixtureArchiveBytes.Length
                    expired = $false
                    digest = $State.ArtifactDigest
                    workflow_run = [ordered]@{ id = $runId }
                }
            }
            $payload = [ordered]@{
                total_count = $artifacts.Count + [int]$State.TotalCountDelta
                artifacts = $artifacts
            }
        }
        else {
            return [pscustomobject]@{
                ExitCode = 2
                Output = @("unexpected gh invocation")
            }
        }

        return [pscustomobject]@{
            ExitCode = 0
            Output = @($payload | ConvertTo-Json -Depth 8 -Compress)
        }
    }.GetNewClosure()
}

function Assert-Rejected {
    param(
        [Parameter(Mandatory = $true)]
        [object]$State,

        [Parameter(Mandatory = $true)]
        [string]$Description,

        [Parameter(Mandatory = $true)]
        [string]$EvidencePath,

        [Parameter(Mandatory = $true)]
        [object]$Evidence
    )

    $rejected = $false
    try {
        Assert-AuthenticatedHardwareEvidence `
            -GhPath "gh.exe" `
            -ExpectedRepository $expectedRepository `
            -ExpectedCommit $commit `
            -Evidence $Evidence `
            -LocalEvidencePath $EvidencePath `
            -PythonPath "fixture-python.exe" `
            -HardwareEvidenceValidatorPath "fixture-validator.py" `
            -GhInvoker (New-MockGhInvoker -State $State) `
            -EvidenceValidator (New-MockEvidenceValidator -State $State) `
            -ArtifactDownloader (
                New-MockArtifactDownloader -State $State
            ) | Out-Null
    }
    catch {
        $rejected = $true
    }
    if (-not $rejected) {
        throw "Authenticated hardware evidence accepted $Description."
    }
    if (
        $null -ne $State.LastDownloadDirectory -and
        (Test-Path -LiteralPath $State.LastDownloadDirectory)
    ) {
        throw "Private download directory was not cleaned after $Description."
    }
}

$testRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("dupez-hardware-evidence-contract-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    $evidencePath = Join-Path $testRoot "hardware-smoketest-evidence.json"
    [IO.File]::WriteAllBytes($evidencePath, $fixtureBytes)
    $evidence = [pscustomobject]@{
        invocation = [pscustomobject]@{
            run_id = [string]$runId
            run_attempt = [string]$runAttempt
        }
    }

    $validState = New-TestState
    $attestation = Assert-AuthenticatedHardwareEvidence `
        -GhPath "gh.exe" `
        -ExpectedRepository $expectedRepository `
        -ExpectedCommit $commit `
        -Evidence $evidence `
        -LocalEvidencePath $evidencePath `
        -PythonPath "fixture-python.exe" `
        -HardwareEvidenceValidatorPath "fixture-validator.py" `
        -GhInvoker (New-MockGhInvoker -State $validState) `
        -EvidenceValidator (New-MockEvidenceValidator -State $validState) `
        -ArtifactDownloader (New-MockArtifactDownloader -State $validState)
    if (
        [int64]$attestation.Attestation.run_id -ne $runId -or
        [int64]$attestation.Attestation.run_attempt -ne $runAttempt -or
        [int64]$attestation.Attestation.artifact_id -ne $artifactId -or
        [string]$attestation.Attestation.artifact_name -cne $artifactName -or
        [string]$attestation.Attestation.artifact_archive_sha256 -cne
            $fixtureArchiveSha256 -or
        [string]$attestation.Attestation.evidence_sha256 -cne (
            Get-Sha256 -Path $evidencePath
        ) -or
        [string]$attestation.Evidence.invocation.run_id -cne [string]$runId
    ) {
        throw "Valid authenticated evidence returned the wrong attestation."
    }
    if ($validState.DownloadInvocations -ne 1) {
        throw "Valid evidence was not downloaded exactly once."
    }
    if ([int64]$validState.DownloadedArtifactId -ne $artifactId) {
        throw "Valid evidence was not downloaded by exact artifact ID."
    }
    if (
        -not $validState.PrivateAclProtected -or
        -not $validState.PrivateAclOnlyCurrentUser
    ) {
        throw "Evidence download directory ACL was not private."
    }
    if ($validState.ValidatorInvocations -ne 1) {
        throw "The authenticated downloaded copy was not validated exactly once."
    }
    if (Test-Path -LiteralPath $validState.LastDownloadDirectory) {
        throw "Private download directory was not cleaned after success."
    }

    $wrongEvent = New-TestState
    $wrongEvent.Event = "push"
    Assert-Rejected $wrongEvent "a push-triggered run" $evidencePath $evidence

    $wrongCommit = New-TestState
    $wrongCommit.HeadSha = "b" * 40
    Assert-Rejected $wrongCommit "a run for another commit" $evidencePath $evidence

    $wrongWorkflow = New-TestState
    $wrongWorkflow.WorkflowPath = ".github/workflows/forged.yml"
    Assert-Rejected $wrongWorkflow "another workflow identity" $evidencePath $evidence

    $missingArtifact = New-TestState
    $missingArtifact.MatchingArtifactCount = 0
    Assert-Rejected $missingArtifact "a missing artifact" $evidencePath $evidence

    $duplicateArtifact = New-TestState
    $duplicateArtifact.MatchingArtifactCount = 2
    Assert-Rejected $duplicateArtifact "duplicate artifacts" $evidencePath $evidence

    $incompleteListing = New-TestState
    $incompleteListing.TotalCountDelta = 1
    Assert-Rejected $incompleteListing "an incomplete artifact listing" $evidencePath $evidence

    $wrongBytes = New-TestState
    $wrongBytes.DownloadBytes = [Text.Encoding]::UTF8.GetBytes("forged")
    Assert-Rejected $wrongBytes "a byte-mismatched artifact" $evidencePath $evidence

    $wrongDigest = New-TestState
    $wrongDigest.ArtifactDigest = "sha256:" + ("b" * 64)
    Assert-Rejected `
        $wrongDigest `
        "an archive that disagrees with the listed digest" `
        $evidencePath `
        $evidence

    $unexpectedArchive = New-TestState
    $unexpectedArchive.DownloadBytes = New-FixtureArchiveBytes `
        -EvidenceBytes $fixtureBytes `
        -IncludeUnexpectedEntry
    $unexpectedArchive.ArtifactDigest = (
        "sha256:" + (
            Get-BytesSha256 -Bytes $unexpectedArchive.DownloadBytes
        )
    )
    Assert-Rejected `
        $unexpectedArchive `
        "an exact-ID archive with unexpected contents" `
        $evidencePath `
        $evidence

    $sourceRoot = Join-Path $testRoot "snapshot-source"
    New-Item -ItemType Directory -Path $sourceRoot | Out-Null
    [IO.File]::WriteAllBytes(
        (Join-Path $sourceRoot "first.bin"),
        [Text.Encoding]::UTF8.GetBytes("validated-first")
    )
    [IO.File]::WriteAllBytes(
        (Join-Path $sourceRoot "second.json"),
        [Text.Encoding]::UTF8.GetBytes('{"validated":true}')
    )
    $snapshotRoot = New-PrivateStageDirectory -Purpose "release-upload"
    try {
        $snapshots = @(
            Copy-ReleaseAssetSnapshot `
                -SourceRoot $sourceRoot `
                -DestinationRoot $snapshotRoot `
                -Names @("first.bin", "second.json")
        )
        $binding = Get-ReleaseAssetBinding -Assets $snapshots
        Assert-ReleaseAssetBinding `
            -Assets $snapshots `
            -Hashes $binding.Hashes `
            -Lengths $binding.Lengths `
            -Description "Fixture snapshot"

        $snapshotLocks = @(Open-ReleaseAssetReadLocks -Assets $snapshots)
        try {
            Assert-ReleaseAssetBinding `
                -Assets $snapshots `
                -Hashes $binding.Hashes `
                -Lengths $binding.Lengths `
                -Description "Locked fixture snapshot"

            # Mutating dist/source after the snapshot cannot affect bound bytes.
            [IO.File]::WriteAllBytes(
                (Join-Path $sourceRoot "first.bin"),
                [Text.Encoding]::UTF8.GetBytes("swapped-after-validation")
            )
            Assert-ReleaseAssetBinding `
                -Assets $snapshots `
                -Hashes $binding.Hashes `
                -Lengths $binding.Lengths `
                -Description "Fixture snapshot after source swap"

            $lockedWriteRejected = $false
            try {
                [IO.File]::WriteAllBytes(
                    (Join-Path $snapshotRoot "first.bin"),
                    [Text.Encoding]::UTF8.GetBytes("swap-only-during-upload")
                )
            }
            catch [System.IO.IOException] {
                $lockedWriteRejected = $true
            }
            if (-not $lockedWriteRejected) {
                throw "A same-user writer changed a locked release snapshot."
            }
        }
        finally {
            foreach ($lock in $snapshotLocks) {
                $lock.Dispose()
            }
        }

        [IO.File]::WriteAllBytes(
            (Join-Path $snapshotRoot "first.bin"),
            [Text.Encoding]::UTF8.GetBytes("snapshot-tampered")
        )
        $snapshotRejected = $false
        try {
            Assert-ReleaseAssetBinding `
                -Assets @(
                    Get-ChildItem -LiteralPath $snapshotRoot -Force
                ) `
                -Hashes $binding.Hashes `
                -Lengths $binding.Lengths `
                -Description "Tampered fixture snapshot"
        }
        catch {
            $snapshotRejected = $true
        }
        if (-not $snapshotRejected) {
            throw "A changed private release snapshot matched its captured binding."
        }
    }
    finally {
        if (Test-Path -LiteralPath $snapshotRoot) {
            Remove-PrivateStageDirectory -Path $snapshotRoot
        }
    }

    $guardRejected = $false
    try {
        Remove-PrivateStageDirectory -Path $testRoot
    }
    catch {
        $guardRejected = $true
    }
    if (-not $guardRejected -or -not (Test-Path -LiteralPath $testRoot)) {
        throw "Private cleanup path guard accepted an unrelated directory."
    }

    $cleanupRoot = New-PrivateStageDirectory -Purpose "release-verify"
    $lockedCleanupFile = Join-Path $cleanupRoot "locked.bin"
    [IO.File]::WriteAllBytes($lockedCleanupFile, [byte[]](1, 2, 3))
    $cleanupLock = [IO.File]::Open(
        $lockedCleanupFile,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::None
    )
    try {
        $cleanupFailureSurfaced = $false
        try {
            Remove-PrivateStageDirectory -Path $cleanupRoot
        }
        catch {
            $cleanupFailureSurfaced = $true
        }
        if (
            -not $cleanupFailureSurfaced -or
            -not (Test-Path -LiteralPath $cleanupRoot)
        ) {
            throw "Private cleanup failure was silently suppressed."
        }
    }
    finally {
        $cleanupLock.Dispose()
        if (Test-Path -LiteralPath $cleanupRoot) {
            Remove-PrivateStageDirectory -Path $cleanupRoot
        }
    }

    $stageText = Get-Content -LiteralPath $stagePath -Raw
    $preflightLockIndex = $stageText.IndexOf(
        'Open-ReleaseAssetReadLocks -Assets $preflightInputAssets'
    )
    $preflightCallIndex = $stageText.IndexOf(
        '-Description "FINAL DIST RELEASE PREFLIGHT"',
        $preflightLockIndex
    )
    $snapshotCopyIndex = $stageText.IndexOf(
        'Copy-ReleaseAssetSnapshot',
        $preflightCallIndex
    )
    $preflightUnlockIndex = $stageText.IndexOf(
        'foreach ($lock in $preflightInputLocks)',
        $snapshotCopyIndex
    )
    $bindingIndex = $stageText.IndexOf(
        '$snapshotBinding = Get-ReleaseAssetBinding'
    )
    $lockIndex = $stageText.IndexOf(
        'Open-ReleaseAssetReadLocks -Assets $assets',
        $bindingIndex
    )
    $lockedRecheckIndex = $stageText.IndexOf(
        '-Description "Locked release snapshot"',
        $lockIndex
    )
    $uploadIndex = $stageText.IndexOf(
        '-Description "UPLOAD VERIFIED RELEASE ASSETS"',
        $lockedRecheckIndex
    )
    $downloadCheckIndex = $stageText.IndexOf(
        '-Description "Downloaded release"',
        $uploadIndex
    )
    $disposeIndex = $stageText.IndexOf(
        'foreach ($lock in $releaseAssetLocks)',
        $downloadCheckIndex
    )
    $cleanupIndex = $stageText.IndexOf(
        'Remove-PrivateStageDirectory -Path $releaseSnapshotRoot',
        $disposeIndex
    )
    if (
        $preflightLockIndex -lt 0 -or
        $preflightCallIndex -le $preflightLockIndex -or
        $snapshotCopyIndex -le $preflightCallIndex -or
        $preflightUnlockIndex -le $snapshotCopyIndex -or
        $bindingIndex -lt 0 -or
        $lockIndex -le $bindingIndex -or
        $lockedRecheckIndex -le $lockIndex -or
        $uploadIndex -le $lockedRecheckIndex -or
        $downloadCheckIndex -le $uploadIndex -or
        $disposeIndex -le $downloadCheckIndex -or
        $cleanupIndex -le $disposeIndex
    ) {
        throw "Release snapshot locks do not span upload and remote verification."
    }
}
finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host (
    "PASS: hardware evidence is exact-ID authenticated and release assets " +
    "are private-snapshot byte-bound."
)
