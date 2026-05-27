# scripts/release.ps1 -- DupeZ release driver with fail-fast guards.
#
# WHY THIS EXISTS
# ----------------
# The manual release sequence (build -> branch -> commit -> push -> PR ->
# merge -> tag -> gh release create) has silently mis-fired four times
# (v5.6.3, v5.6.5, v5.7.1 twice). The failure mode is always the same:
#
#   1. A pre-commit hook (ruff) fails, so `git commit` exits non-zero
#      and NO commit is created.
#   2. PowerShell does NOT stop on a non-zero exit from an external
#      program -- it keeps running the next line.
#   3. The script proceeds to `git tag` / `gh release create`, which
#      tag whatever HEAD currently is -- i.e. the PREVIOUS release's
#      commit. The new release ships pointing at stale source.
#
# This script makes that impossible. After EVERY git/gh invocation it
# checks $LASTEXITCODE and aborts the whole release on the first
# failure -- before anything irreversible (tag, release) happens. It
# also verifies, with positive assertions, that:
#
#   * the commit actually landed (HEAD moved, working tree clean)
#   * the release branch is genuinely ahead of main before the PR
#   * the tag, once created, points at the just-merged commit
#
# USAGE
# -----
#   .\scripts\release.ps1 -Version 5.7.4
#   .\scripts\release.ps1 -Version 5.7.4 -SkipBuild   # reuse dist/
#
# Run from the repo root. Requires: git, gh, and (unless -SkipBuild)
# a working packaging\build_variants.bat plus DUPEZ_SIGN_PRIVKEY set.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [switch]$SkipBuild,

    # Pre-commit hooks that fail under WDAC / Smart App Control on this
    # box. Skipped via the SKIP env var. Narrow list on purpose -- ruff,
    # detect-private-key, etc. still run and still gate the commit.
    [string]$SkipHooks = "detect-secrets,end-of-file-fixer"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# -- Helper: run a native command, abort the release if it fails ------
function Invoke-Step {
    param(
        [string]$Description,
        [scriptblock]$Action
    )
    Write-Host ""
    Write-Host "--> $Description" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "RELEASE ABORTED -- step failed: $Description" -ForegroundColor Red
        Write-Host "Exit code: $LASTEXITCODE" -ForegroundColor Red
        Write-Host "Nothing irreversible has happened yet if this is" -ForegroundColor Yellow
        Write-Host "before the tag step. Fix the cause and re-run." -ForegroundColor Yellow
        exit 1
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        Write-Host ""
        Write-Host "RELEASE ABORTED -- assertion failed: $Message" -ForegroundColor Red
        exit 1
    }
}

$tag        = "v$Version"
$branch     = "release/$tag"
$installer  = "dist\DupeZ_v${Version}_Setup.exe"
$notesFile  = "docs\release-notes\$tag.md"

Write-Host "============================================" -ForegroundColor Green
Write-Host " DupeZ release driver -- $tag" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

# -- 0. Pre-flight ----------------------------------------------------
if (-not (Test-Path ".git")) {
    Write-Host "ERROR: run this from the repo root." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $notesFile)) {
    Write-Host "ERROR: release notes not found: $notesFile" -ForegroundColor Red
    Write-Host "Create the release-notes file before releasing." -ForegroundColor Yellow
    exit 1
}

# -- 1. Build ---------------------------------------------------------
if ($SkipBuild) {
    Write-Host "--> Skipping build (-SkipBuild); reusing dist\" -ForegroundColor Yellow
} else {
    Invoke-Step "Building variants + installer + signed manifest" {
        & packaging\build_variants.bat
    }
}

# Verify the artifacts the release needs actually exist.
$required = @(
    "dist\DupeZ-GPU.exe",
    "dist\DupeZ-Compat.exe",
    $installer,
    "dist\DupeZ_Setup.exe",
    "dist\DupeZ_Setup.exe.manifest.json",
    "dist\DupeZ_Setup.exe.manifest.sig"
)
foreach ($f in $required) {
    Assert-True (Test-Path $f) "required artifact missing: $f"
}
Write-Host "  all 6 release artifacts present." -ForegroundColor Green

# -- 2. Branch --------------------------------------------------------
$headBefore = (git rev-parse HEAD).Trim()
Invoke-Step "Creating release branch $branch" {
    git checkout -b $branch
}

# -- 3. Commit (the step that has silently failed four times) ---------
Invoke-Step "Staging all changes" { git add -A }

$env:SKIP = $SkipHooks
try {
    Invoke-Step "Committing" {
        git commit -m "$tag release"
    }
} finally {
    Remove-Item Env:SKIP -ErrorAction SilentlyContinue
}

# POSITIVE assertion: the commit actually moved HEAD. If a hook ate the
# commit, HEAD would be unchanged -- catch it here, before the tag.
$headAfter = (git rev-parse HEAD).Trim()
Assert-True ($headAfter -ne $headBefore) `
    "HEAD did not move after commit -- the commit did not land (hook failure?)"
$dirty = (git status --porcelain)
Assert-True ([string]::IsNullOrWhiteSpace($dirty)) `
    "working tree still dirty after commit -- staged changes were not all committed"
Write-Host "  commit landed: $headAfter" -ForegroundColor Green

# -- 4. Push + PR + merge ---------------------------------------------
Invoke-Step "Pushing $branch" { git push -u origin $branch }

Invoke-Step "Opening pull request" {
    gh pr create --title "$tag" --body "Automated release. See docs/release-notes/$tag.md and CHANGELOG.md."
}
Invoke-Step "Squash-merging pull request" {
    gh pr merge --squash --delete-branch
}

# -- 5. Re-sync main + tag ON THE MERGED COMMIT -----------------------
Invoke-Step "Returning to main" { git checkout main }
Invoke-Step "Pulling merged commit" { git pull origin main }

$mergedCommit = (git rev-parse HEAD).Trim()
# The merged commit must differ from where main was before this release.
Assert-True ($mergedCommit -ne $headBefore) `
    "main HEAD unchanged after merge -- the squash-merge did not land"

Invoke-Step "Tagging $tag on $mergedCommit" {
    git tag -a $tag -m "$tag"
}
Invoke-Step "Pushing tag" { git push origin $tag }

# Verify the tag dereferences to the commit we just merged.
$tagCommit = (git rev-list -n 1 $tag).Trim()
Assert-True ($tagCommit -eq $mergedCommit) `
    "tag $tag points at $tagCommit, expected merged commit $mergedCommit"
Write-Host "  tag $tag verified on $tagCommit" -ForegroundColor Green

# -- 6. Cut the GitHub release ----------------------------------------
Invoke-Step "Creating GitHub release" {
    gh release create $tag `
        dist\DupeZ-GPU.exe `
        dist\DupeZ-Compat.exe `
        $installer `
        dist\DupeZ_Setup.exe `
        dist\DupeZ_Setup.exe.manifest.json `
        dist\DupeZ_Setup.exe.manifest.sig `
        --title "$tag" `
        --notes-file $notesFile
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " $tag SHIPPED -- tag on $tagCommit, 6 assets" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
exit 0
