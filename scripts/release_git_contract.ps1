#requires -Version 5.1

# Shared, fail-closed Git provenance for release consumers.  Release scripts
# must never resolve Git from PATH or inherit repository/config overrides.

$script:DupeZTrustedReleaseGit = $null

function Assert-ReleasePathIsNonReparse {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [switch]$RequireLeaf
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Release provenance path is not absolute."
    }
    $cursor = $root
    $tail = $fullPath.Substring($root.Length)
    foreach ($part in @($tail -split '[\\/]' | Where-Object { $_ })) {
        $cursor = Join-Path $cursor $part
        if (-not (Test-Path -LiteralPath $cursor)) {
            if ($RequireLeaf -or $cursor -cne $fullPath) {
                throw "Release provenance path is unavailable."
            }
            return
        }
        $item = Get-Item -LiteralPath $cursor -Force
        if (
            ($item.Attributes -band
                [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "Release provenance refuses reparse-point paths."
        }
    }
}

function Resolve-TrustedReleaseGit {
    [CmdletBinding()]
    param()

    if ($script:DupeZTrustedReleaseGit) {
        return $script:DupeZTrustedReleaseGit
    }

    $programFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::ProgramFiles
    )
    if ([string]::IsNullOrWhiteSpace($programFiles)) {
        throw "The trusted Program Files directory is unavailable."
    }
    foreach ($relative in @("Git\cmd\git.exe", "Git\bin\git.exe")) {
        $candidate = [System.IO.Path]::GetFullPath((
            Join-Path $programFiles $relative
        ))
        try {
            Assert-ReleasePathIsNonReparse -Path $candidate -RequireLeaf
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                continue
            }
            $item = Get-Item -LiteralPath $candidate -Force
            if ($item.Name -cne "git.exe" -or $item.Length -le 0) {
                continue
            }
            $script:DupeZTrustedReleaseGit = $item.FullName
            return $script:DupeZTrustedReleaseGit
        }
        catch {
            continue
        }
    }
    throw "Trusted Git for Windows is unavailable under Program Files."
}

function Get-ReleaseGitOverrideNames {
    [CmdletBinding()]
    param()

    $exact = @(
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_EXEC_PATH",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_WORK_TREE"
    )
    return @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).Keys |
            ForEach-Object { ([string]$_).ToUpperInvariant() } |
            Where-Object {
                $_ -in $exact -or
                $_.StartsWith("GIT_CONFIG_", [StringComparison]::Ordinal) -or
                $_.StartsWith(
                    "GIT_OBJECT_DIRECTORY_",
                    [StringComparison]::Ordinal
                )
            } |
            Sort-Object -Unique
    )
}

function Assert-NoReleaseGitOverrides {
    [CmdletBinding()]
    param()

    $overrides = @(Get-ReleaseGitOverrideNames)
    if ($overrides.Count -gt 0) {
        throw (
            "Release provenance refuses inherited Git overrides. Unset: " +
            ($overrides -join ", ")
        )
    }
}

function Invoke-TrustedReleaseGit {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [int[]]$AllowedExitCodes = @(0)
    )

    Assert-NoReleaseGitOverrides
    $repository = [System.IO.Path]::GetFullPath($RepositoryRoot)
    Assert-ReleasePathIsNonReparse -Path $repository -RequireLeaf
    if (-not (Test-Path -LiteralPath $repository -PathType Container)) {
        throw "Release provenance repository is unavailable."
    }
    $git = Resolve-TrustedReleaseGit

    $safeEnvironment = [ordered]@{
        GIT_CONFIG_NOSYSTEM = "1"
        GIT_CONFIG_GLOBAL = "NUL"
        GIT_OPTIONAL_LOCKS = "0"
        GIT_NO_REPLACE_OBJECTS = "1"
        GIT_TERMINAL_PROMPT = "0"
        GCM_INTERACTIVE = "Never"
    }
    $saved = @{}
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        foreach ($name in $safeEnvironment.Keys) {
            $saved[$name] = [Environment]::GetEnvironmentVariable(
                $name,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                $name,
                $safeEnvironment[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
        $ErrorActionPreference = "Continue"
        $output = @(
            & $git `
                --no-pager `
                --no-replace-objects `
                -c core.fsmonitor=false `
                -c core.untrackedCache=false `
                -c core.excludesFile=NUL `
                -c core.attributesFile=NUL `
                -C $repository `
                @Arguments 2>$null
        )
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
        foreach ($name in $safeEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $saved[$name],
                [EnvironmentVariableTarget]::Process
            )
        }
    }
    if ($exitCode -notin $AllowedExitCodes) {
        throw "Trusted Git provenance command failed with exit code $exitCode."
    }
    return $output
}

function Assert-ReleaseGitMetadataFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot
    )

    $gitDirectory = Join-Path $RepositoryRoot ".git"
    Assert-ReleasePathIsNonReparse -Path $gitDirectory -RequireLeaf
    if (-not (Test-Path -LiteralPath $gitDirectory -PathType Container)) {
        throw "Release provenance requires a normal .git directory."
    }
    foreach ($relative in @("config", "index")) {
        $path = Join-Path $gitDirectory $relative
        Assert-ReleasePathIsNonReparse -Path $path -RequireLeaf
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Release provenance Git metadata is incomplete."
        }
    }

    $infoDirectory = Join-Path $gitDirectory "info"
    Assert-ReleasePathIsNonReparse -Path $infoDirectory -RequireLeaf
    if (-not (Test-Path -LiteralPath $infoDirectory -PathType Container)) {
        throw "Release provenance Git info directory is unavailable."
    }
    $attributesPath = Join-Path $infoDirectory "attributes"
    if (Test-Path -LiteralPath $attributesPath) {
        Assert-ReleasePathIsNonReparse -Path $attributesPath -RequireLeaf
        $attributes = Get-Item -LiteralPath $attributesPath -Force
        if ($attributes.PSIsContainer -or $attributes.Length -ne 0) {
            throw "Release provenance refuses .git/info/attributes."
        }
    }
    $excludePath = Join-Path $infoDirectory "exclude"
    if (Test-Path -LiteralPath $excludePath) {
        Assert-ReleasePathIsNonReparse -Path $excludePath -RequireLeaf
        $exclude = Get-Item -LiteralPath $excludePath -Force
        if ($exclude.PSIsContainer -or $exclude.Length -gt 65536) {
            throw "Release provenance Git exclude metadata is invalid."
        }
        $patterns = @(
            Get-Content -LiteralPath $excludePath |
                Where-Object {
                    -not [string]::IsNullOrWhiteSpace($_) -and
                    -not $_.TrimStart().StartsWith(
                        "#",
                        [StringComparison]::Ordinal
                    )
                }
        )
        if ($patterns.Count -gt 0) {
            throw "Release provenance refuses .git/info/exclude patterns."
        }
    }
}

function Get-ReleaseGitIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [string]$RequiredBranch = "main",

        [switch]$AllowDirty
    )

    Assert-NoReleaseGitOverrides
    $repository = [System.IO.Path]::GetFullPath($RepositoryRoot)
    Assert-ReleaseGitMetadataFiles -RepositoryRoot $repository

    $topLevel = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("rev-parse", "--show-toplevel")
    )
    if (
        $topLevel.Count -ne 1 -or
        -not [StringComparer]::OrdinalIgnoreCase.Equals(
            [System.IO.Path]::GetFullPath([string]$topLevel[0]),
            $repository
        )
    ) {
        throw "Git provenance resolved a different repository root."
    }
    $gitDirectory = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("rev-parse", "--absolute-git-dir")
    )
    $expectedGitDirectory = [System.IO.Path]::GetFullPath((
        Join-Path $repository ".git"
    ))
    if (
        $gitDirectory.Count -ne 1 -or
        -not [StringComparer]::OrdinalIgnoreCase.Equals(
            [System.IO.Path]::GetFullPath([string]$gitDirectory[0]),
            $expectedGitDirectory
        )
    ) {
        throw "Git provenance resolved a different Git directory."
    }

    $headRef = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("symbolic-ref", "--quiet", "HEAD")
    )
    if (
        $headRef.Count -ne 1 -or
        [string]$headRef[0] -cnotmatch '^refs/heads/(?<branch>[^\r\n]+)$'
    ) {
        throw "Release provenance requires an attached local branch."
    }
    $branch = [string]$Matches.branch
    if (
        -not [string]::IsNullOrWhiteSpace($RequiredBranch) -and
        $branch -cne $RequiredBranch
    ) {
        throw "Release provenance requires branch $RequiredBranch."
    }
    $commitOutput = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("rev-parse", "--verify", "HEAD^{commit}")
    )
    if (
        $commitOutput.Count -ne 1 -or
        [string]$commitOutput[0] -cnotmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$'
    ) {
        throw "Release provenance could not resolve a canonical commit."
    }
    $commit = ([string]$commitOutput[0]).ToLowerInvariant()

    $replacementRefs = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @(
                "for-each-ref",
                "--format=%(refname)",
                "refs/replace"
            )
    )
    if ($replacementRefs.Count -gt 0) {
        throw "Release provenance refuses Git replacement refs."
    }
    $sparse = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("config", "--bool", "--get", "core.sparseCheckout") `
            -AllowedExitCodes @(0, 1)
    )
    if ($sparse.Count -gt 0 -and $sparse[0] -ceq "true") {
        throw "Release provenance refuses sparse checkouts."
    }
    $unsafeConfiguration = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @(
                "config",
                "--local",
                "--name-only",
                "--get-regexp",
                (
                    "^(filter\.|core\.(attributesfile|excludesfile|" +
                    "worktree)$|include\.|includeif\.|" +
                    "extensions\.worktreeconfig$)"
                )
            ) `
            -AllowedExitCodes @(0, 1)
    )
    if ($unsafeConfiguration.Count -gt 0) {
        throw "Release provenance refuses local Git filter/include/worktree configuration."
    }

    $indexFlags = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("ls-files", "-v")
    )
    foreach ($line in $indexFlags) {
        if (
            $line.Length -lt 3 -or
            $line[1] -ne ' ' -or
            $line[0] -ceq 'S' -or
            [char]::IsLower($line[0])
        ) {
            throw "Release provenance refuses skip-worktree or assume-unchanged entries."
        }
    }

    $headEntries = New-Object `
        'System.Collections.Generic.Dictionary[string,object]' `
        ([StringComparer]::Ordinal)
    $treeLines = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("ls-tree", "-r", "--full-tree", "HEAD")
    )
    foreach ($line in $treeLines) {
        if (
            $line -notmatch (
                '^(?<mode>[0-9]{6}) (?<type>[^ ]+) ' +
                '(?<oid>(?:[0-9a-f]{40}|[0-9a-f]{64}))\t(?<path>.+)$'
            )
        ) {
            throw "Git HEAD tree metadata is malformed."
        }
        $relative = [string]$Matches.path
        if (
            $Matches.type -cne "blob" -or
            $Matches.mode -notin @("100644", "100755") -or
            $relative.StartsWith('"', [StringComparison]::Ordinal) -or
            $relative.Contains("`r") -or
            $relative.Contains("`n") -or
            $headEntries.ContainsKey($relative)
        ) {
            throw "Release provenance refuses special or unsafe tracked paths."
        }
        $headEntries.Add(
            $relative,
            [pscustomobject]@{
                Mode = [string]$Matches.mode
                Oid = [string]$Matches.oid
            }
        )
    }
    if ($headEntries.Count -lt 1) {
        throw "Release provenance HEAD tree is empty."
    }

    $indexEntries = New-Object `
        'System.Collections.Generic.Dictionary[string,object]' `
        ([StringComparer]::Ordinal)
    $indexLines = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("ls-files", "-s")
    )
    foreach ($line in $indexLines) {
        if (
            $line -notmatch (
                '^(?<mode>[0-9]{6}) ' +
                '(?<oid>(?:[0-9a-f]{40}|[0-9a-f]{64})) ' +
                '(?<stage>[0-3])\t(?<path>.+)$'
            )
        ) {
            throw "Git index metadata is malformed."
        }
        $relative = [string]$Matches.path
        if (
            $Matches.stage -cne "0" -or
            $relative.StartsWith('"', [StringComparison]::Ordinal) -or
            $indexEntries.ContainsKey($relative)
        ) {
            throw "Release provenance index is unresolved or unsafe."
        }
        $indexEntries.Add(
            $relative,
            [pscustomobject]@{
                Mode = [string]$Matches.mode
                Oid = [string]$Matches.oid
            }
        )
    }
    $sourceClean = $true
    if ($indexEntries.Count -ne $headEntries.Count) {
        if (-not $AllowDirty) {
            throw "Release provenance index does not exactly match HEAD."
        }
        $sourceClean = $false
    }

    foreach ($relative in $headEntries.Keys) {
        if (-not $indexEntries.ContainsKey($relative)) {
            if (-not $AllowDirty) {
                throw "Release provenance index omits a HEAD path."
            }
            $sourceClean = $false
            continue
        }
        $head = $headEntries[$relative]
        $index = $indexEntries[$relative]
        if ($head.Mode -cne $index.Mode -or $head.Oid -cne $index.Oid) {
            if (-not $AllowDirty) {
                throw "Release provenance index differs from HEAD."
            }
            $sourceClean = $false
        }

        $candidate = [System.IO.Path]::GetFullPath((
            Join-Path $repository ($relative.Replace('/', '\'))
        ))
        $repositoryPrefix = $repository.TrimEnd('\') + '\'
        if (-not $candidate.StartsWith(
            $repositoryPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Release provenance tracked path escaped the repository."
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            if (-not $AllowDirty) {
                throw "Release provenance tracked file is unavailable."
            }
            $sourceClean = $false
            continue
        }
        Assert-ReleasePathIsNonReparse -Path $candidate -RequireLeaf

        $filter = @(
            Invoke-TrustedReleaseGit `
                -RepositoryRoot $repository `
                -Arguments @("check-attr", "filter", "--", $relative)
        )
        if (
            $filter.Count -ne 1 -or
            (
                -not $filter[0].EndsWith(
                    ": filter: unspecified",
                    [StringComparison]::Ordinal
                ) -and
                -not $filter[0].EndsWith(
                    ": filter: unset",
                    [StringComparison]::Ordinal
                )
            )
        ) {
            throw "Release provenance refuses custom Git clean filters."
        }
        $workingHash = @(
            Invoke-TrustedReleaseGit `
                -RepositoryRoot $repository `
                -Arguments @("hash-object", "--", $relative)
        )
        if (
            $workingHash.Count -ne 1 -or
            [string]$workingHash[0] -cne $head.Oid
        ) {
            if (-not $AllowDirty) {
                throw "Release provenance tracked bytes differ from HEAD."
            }
            $sourceClean = $false
        }
    }

    $status = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @(
                "status",
                "--porcelain=v1",
                "--untracked-files=all"
            )
    )
    if ($status.Count -gt 0) {
        if (-not $AllowDirty) {
            throw "Release provenance requires a clean source tree."
        }
        $sourceClean = $false
    }
    $commitAfter = @(
        Invoke-TrustedReleaseGit `
            -RepositoryRoot $repository `
            -Arguments @("rev-parse", "--verify", "HEAD^{commit}")
    )
    if ($commitAfter.Count -ne 1 -or $commitAfter[0] -cne $commit) {
        throw "Release provenance changed during verification."
    }

    return [pscustomobject]@{
        Git = Resolve-TrustedReleaseGit
        Branch = $branch
        Commit = $commit
        SourceState = if ($sourceClean) { "clean" } else { "dirty" }
        Clean = $sourceClean
    }
}

function Assert-ReleaseGitIdentityUnchanged {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommit,

        [string]$RequiredBranch = "main"
    )

    $identity = Get-ReleaseGitIdentity `
        -RepositoryRoot $RepositoryRoot `
        -RequiredBranch $RequiredBranch
    if ($identity.Commit -cne $ExpectedCommit) {
        throw "Release source identity changed after validation began."
    }
    return $identity
}
