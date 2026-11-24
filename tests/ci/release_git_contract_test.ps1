#requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
. (Join-Path $repoRoot "scripts\release_git_contract.ps1")

$git = Resolve-TrustedReleaseGit
$savedOverrides = @{}
foreach ($name in @(Get-ReleaseGitOverrideNames)) {
    $savedOverrides[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        $name,
        $null,
        [EnvironmentVariableTarget]::Process
    )
}
$testRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("dupez-release-git-contract-" + [Guid]::NewGuid().ToString("N"))
$fixture = Join-Path $testRoot "repo"

function Invoke-FixtureGit {
    param([string[]]$Arguments)

    & $git `
        --no-pager `
        --no-replace-objects `
        -c core.fsmonitor=false `
        -c core.untrackedCache=false `
        -C $fixture `
        @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Fixture Git command failed: $($Arguments -join ' ')"
    }
}

function Assert-ThrowsLike {
    param(
        [scriptblock]$Action,
        [string]$Pattern
    )

    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) {
            throw
        }
        return
    }
    throw "Expected failure matching: $Pattern"
}

New-Item -ItemType Directory -Path $testRoot | Out-Null
try {
    & $git init --initial-branch=main $fixture | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not initialize the Git contract fixture."
    }
    Invoke-FixtureGit -Arguments @("config", "user.name", "DupeZ Contract")
    Invoke-FixtureGit -Arguments @("config", "user.email", "contract@example.invalid")
    [System.IO.File]::WriteAllText(
        (Join-Path $fixture ".gitattributes"),
        "*.ps1 text eol=crlf`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $fixture "release.ps1"),
        "Write-Output 'fixture'`r`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    Invoke-FixtureGit -Arguments @("add", "--", ".gitattributes", "release.ps1")
    Invoke-FixtureGit -Arguments @("commit", "-m", "initial")
    [System.IO.File]::WriteAllText(
        (Join-Path $fixture "second.txt"),
        "second`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    Invoke-FixtureGit -Arguments @("add", "--", "second.txt")
    Invoke-FixtureGit -Arguments @("commit", "-m", "second")

    $identity = Get-ReleaseGitIdentity `
        -RepositoryRoot $fixture `
        -RequiredBranch "main"
    if (
        $identity.Branch -cne "main" -or
        $identity.SourceState -cne "clean" -or
        $identity.Commit -cnotmatch '^[0-9a-f]{40}$'
    ) {
        throw "Clean Git identity did not match the fixture."
    }

    $savedGitDir = $env:GIT_DIR
    try {
        $env:GIT_DIR = "must-not-be-used"
        Assert-ThrowsLike `
            -Pattern "inherited Git overrides" `
            -Action {
                Get-ReleaseGitIdentity `
                    -RepositoryRoot $fixture `
                    -RequiredBranch "main" | Out-Null
            }
    }
    finally {
        $env:GIT_DIR = $savedGitDir
    }

    $head = @(
        & $git --no-replace-objects -C $fixture rev-parse HEAD
    )[0]
    $parent = @(
        & $git --no-replace-objects -C $fixture rev-parse HEAD^
    )[0]
    Invoke-FixtureGit -Arguments @("replace", [string]$head, [string]$parent)
    Assert-ThrowsLike `
        -Pattern "replacement refs" `
        -Action {
            Get-ReleaseGitIdentity `
                -RepositoryRoot $fixture `
                -RequiredBranch "main" | Out-Null
        }
    Invoke-FixtureGit -Arguments @("replace", "-d", [string]$head)

    Invoke-FixtureGit -Arguments @("config", "extensions.worktreeConfig", "true")
    Assert-ThrowsLike `
        -Pattern "worktree configuration" `
        -Action {
            Get-ReleaseGitIdentity `
                -RepositoryRoot $fixture `
                -RequiredBranch "main" | Out-Null
        }
    Invoke-FixtureGit -Arguments @("config", "--unset", "extensions.worktreeConfig")

    Add-Content -LiteralPath (Join-Path $fixture "second.txt") -Value "dirty"
    $dirtyIdentity = Get-ReleaseGitIdentity `
        -RepositoryRoot $fixture `
        -RequiredBranch "main" `
        -AllowDirty
    if ($dirtyIdentity.Clean -or $dirtyIdentity.SourceState -cne "dirty") {
        throw "Dirty progress identity was not marked dirty."
    }
    Assert-ThrowsLike `
        -Pattern "tracked bytes differ|clean source tree" `
        -Action {
            Get-ReleaseGitIdentity `
                -RepositoryRoot $fixture `
                -RequiredBranch "main" | Out-Null
        }

    Write-Output "PASS: trusted release Git contract rejects provenance substitution."
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
    foreach ($name in $savedOverrides.Keys) {
        [Environment]::SetEnvironmentVariable(
            $name,
            $savedOverrides[$name],
            [EnvironmentVariableTarget]::Process
        )
    }
}
