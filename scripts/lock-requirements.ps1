<#
.SYNOPSIS
    Regenerate requirements-locked.txt from requirements.in with wheel hashes.

.DESCRIPTION
    Pins every direct and transitive dependency to a single wheel hash
    so `pip install --require-hashes` can verify supply-chain integrity.

    Run this after:
      - Editing requirements.in
      - Bumping a dependency version
      - Pre-release gate (Windows wheels must be resolved on Windows)

.EXAMPLE
    .\scripts\lock-requirements.ps1

.NOTES
    Requires pip-tools.  Installed automatically if missing.
#>

param(
    [switch]$Upgrade,   # pass --upgrade to pip-compile
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "==> Ensuring pip-tools is installed..."
& $Python -m pip install --quiet --upgrade pip-tools

$compileArgs = @(
    "-m", "piptools", "compile",
    "--generate-hashes",
    "--resolver=backtracking",
    "--output-file=requirements-locked.txt",
    "requirements.in"
)
if ($Upgrade) { $compileArgs += "--upgrade" }

Write-Host "==> Regenerating requirements-locked.txt with hashes..."
& $Python @compileArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "pip-compile failed."
    exit $LASTEXITCODE
}

Write-Host "==> Verifying lockfile is installable with --require-hashes..."
& $Python -m pip install --dry-run --require-hashes --quiet -r requirements-locked.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Lockfile verification failed — do NOT commit."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "OK — requirements-locked.txt regenerated and verified." -ForegroundColor Green
Write-Host "Commit requirements.in AND requirements-locked.txt together."
