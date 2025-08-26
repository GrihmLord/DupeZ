param(
  [switch]$Admin
)

# DupeZ - Unified PowerShell Launcher
# Usage:
#   .\dupez.ps1            # normal
#   .\dupez.ps1 -Admin     # elevated

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

function Start-Elevated {
  param([string]$FilePath, [string[]]$Args)
  Start-Process -FilePath $FilePath -ArgumentList $Args -Verb RunAs | Out-Null
}

# Locate packaged exe (update if renamed)
$exePath = Join-Path $here 'dist/DupeZ_izurvive/DupeZ_izurvive.exe'
if (-not (Test-Path $exePath)) {
  $exe = Get-ChildItem -Path (Join-Path $here 'dist') -Filter *.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($exe) { $exePath = $exe.FullName }
}

# Prefer venv python for source runs
$venvPy = Join-Path $here '.venv/Scripts/python.exe'

if ($Admin) {
  Write-Host 'Starting DupeZ (Admin)...'
  if (Test-Path $exePath) {
    Start-Elevated -FilePath $exePath -Args @()
    exit 0
  }
  if (Test-Path $venvPy) {
    Start-Elevated -FilePath $venvPy -Args @('-m','app.main')
    exit 0
  }
  Start-Elevated -FilePath 'python' -Args @('-m','app.main')
  exit 0
}
else {
  Write-Host 'Starting DupeZ (Normal)...'
  if (Test-Path $exePath) {
    Start-Process -FilePath $exePath | Out-Null
    exit 0
  }
  if (Test-Path $venvPy) {
    & $venvPy -m app.main
  } else {
    python -m app.main
  }
}




