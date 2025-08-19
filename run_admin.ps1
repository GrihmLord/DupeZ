# DupeZ Admin Launcher - PowerShell Version
# Ensures Virtual Environment Usage with Admin Privileges

Write-Host "DupeZ Admin Launcher - Starting..." -ForegroundColor Green

# Change to script directory
Set-Location $PSScriptRoot

# Check if running as administrator
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if (-not $IsAdmin) {
    Write-Host "Requesting Administrator privileges..." -ForegroundColor Yellow
    Start-Process PowerShell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Write-Host "Running with Administrator privileges" -ForegroundColor Green

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& ".\.venv\Scripts\Activate.ps1"

# Verify Python environment
Write-Host "Using Python:" -ForegroundColor Cyan
python -c "import sys; print(sys.executable)"

# Check if we're in the correct directory and environment
if (Test-Path ".\.venv\Scripts\python.exe") {
    Write-Host "Virtual environment confirmed" -ForegroundColor Green
} else {
    Write-Host "Virtual environment not found!" -ForegroundColor Red
    pause
    exit 1
}

# Start DupeZ
Write-Host ""
Write-Host "Starting DupeZ Application..." -ForegroundColor Green
Write-Host "Window title will show [ADMIN] when running with admin privileges" -ForegroundColor Cyan
Write-Host ""

try {
    python -m app.main
} catch {
    Write-Host "Error starting application: $_" -ForegroundColor Red
    pause
}
