# scripts/reset_pytest_tmp.ps1 -- one-time pytest temp-dir ACL repair.
#
# WHY THIS EXISTS
# ---------------
# Pytest's default basetemp on Windows is
# %LOCALAPPDATA%\Temp\pytest-of-<USER>. If ANY pytest run was ever
# invoked under an elevated token (typical when dupez.py auto-elevates
# via UAC and a test session inherits the admin token), that directory's
# DACL gets written admin-only. Every subsequent non-elevated pytest run
# then dies with "[WinError 5] Access is denied" at the tmp_path fixture
# -- dozens of bogus errors that have nothing to do with the code.
#
# The long-term fix is in tests/conftest.py: a pytest_configure hook
# pins basetemp to a repo-local .pytest-tmp/ dir, so future pytest runs
# never use the system temp path at all.
#
# This script does the one-time cleanup of the legacy orphan dir that
# pre-existing pytest runs left behind. Run it ONCE from an elevated
# PowerShell. After that, the conftest.py hook ensures it can never
# come back, and you can use a normal (non-elevated) PowerShell forever.
#
# USAGE
# -----
#   Open PowerShell as Administrator, then:
#   .\scripts\reset_pytest_tmp.ps1
#
# To verify it ran from an elevated shell:
#   ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
# should print True.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# -- 0. Confirm elevation ---------------------------------------------
$elevated = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $elevated) {
    Write-Host "ERROR: this script must run from an elevated PowerShell." `
        -ForegroundColor Red
    Write-Host "Right-click PowerShell -> Run as administrator, then re-run." `
        -ForegroundColor Yellow
    exit 1
}

# -- 1. Locate the orphan dir -----------------------------------------
$victim = Join-Path $env:LOCALAPPDATA "Temp\pytest-of-$env:USERNAME"

if (-not (Test-Path $victim)) {
    Write-Host "No orphan pytest temp dir at $victim -- nothing to do." `
        -ForegroundColor Green
    exit 0
}

Write-Host "Found orphan pytest temp dir: $victim" -ForegroundColor Cyan

# -- 2. Take ownership recursively ------------------------------------
Write-Host "Taking ownership..." -ForegroundColor Cyan
takeown /F "$victim" /R /D Y | Out-Null

# -- 3. Grant the current user full control recursively ---------------
Write-Host "Resetting ACL to grant $env:USERNAME full control..." `
    -ForegroundColor Cyan
icacls "$victim" /grant "${env:USERNAME}:(OI)(CI)F" /T /Q | Out-Null

# -- 4. Delete the dir ------------------------------------------------
Write-Host "Deleting..." -ForegroundColor Cyan
Remove-Item "$victim" -Recurse -Force

if (Test-Path $victim) {
    Write-Host "ERROR: dir still exists after delete -- something is holding it open." `
        -ForegroundColor Red
    Write-Host "Close any pytest/python processes and re-run." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Done. The orphan pytest temp dir is gone." -ForegroundColor Green
Write-Host " Future pytest runs will use the repo-local .pytest-tmp/" -ForegroundColor Green
Write-Host " dir pinned by tests/conftest.py -- no more WinError 5." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
exit 0
