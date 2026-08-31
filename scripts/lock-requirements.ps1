<#
.SYNOPSIS
    Regenerate the runtime and unprivileged test locks with wheel hashes.

.DESCRIPTION
    Pins every direct and transitive dependency in requirements.in and
    requirements-test.in so `pip install --require-hashes` can verify
    supply-chain integrity. Run this with the canonical CPython 3.13 on
    Windows so the committed lock headers record the reviewed interpreter.

    Run this after:
      - Editing requirements.in or requirements-test.in
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

Write-Host "==> Ensuring reviewed pip and pip-tools versions are installed..."
& $Python -m pip install --quiet --only-binary=:all: `
    "pip==26.2.1" "pip-tools==7.6.1"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Could not install the reviewed pip and pip-tools versions."
    exit $LASTEXITCODE
}

function New-ReviewedLock {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InputPath,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath,

        [switch]$AllowUnsafe
    )

    $compileArgs = @(
        "-m", "piptools", "compile",
        "--generate-hashes",
        "--resolver=backtracking",
        "--strip-extras",
        "--no-emit-options",
        "--pip-args=--only-binary=:all:",
        "--output-file=$OutputPath",
        $InputPath
    )
    if ($AllowUnsafe) { $compileArgs += "--allow-unsafe" }
    if ($Upgrade) { $compileArgs += "--upgrade" }

    Write-Host "==> Regenerating $OutputPath with hashes..."
    & $Python @compileArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip-compile failed for $InputPath."
        exit $LASTEXITCODE
    }

    & $Python scripts/verify_requirements_lock.py `
        --requirements $InputPath `
        --lock $OutputPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Lock contract verification failed for $OutputPath."
        exit $LASTEXITCODE
    }

    & $Python -m pip install --only-binary=:all: --dry-run `
        --require-hashes --quiet -r $OutputPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Installability verification failed for $OutputPath."
        exit $LASTEXITCODE
    }
}

New-ReviewedLock `
    -InputPath "requirements.in" `
    -OutputPath "requirements-locked.txt"
New-ReviewedLock `
    -InputPath "requirements-test.in" `
    -OutputPath "requirements-test-locked.txt" `
    -AllowUnsafe

Write-Host ""
Write-Host "OK -- runtime and test locks regenerated and verified." -ForegroundColor Green
Write-Host "Commit each requirements input together with its paired lock."
