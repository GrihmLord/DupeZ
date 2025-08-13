# DupeZ Administrator Launcher
# This script runs DupeZ with administrator privileges for full functionality

Write-Host "[ADMIN] Starting DupeZ with Administrator privileges..." -ForegroundColor Green
Write-Host ""
Write-Host "This will allow all features to work properly, including:" -ForegroundColor Yellow
Write-Host "  • Disconnect functionality" -ForegroundColor Cyan
Write-Host "  • UDP interruption" -ForegroundColor Cyan
Write-Host "  • Firewall rules" -ForegroundColor Cyan
Write-Host "  • Network scanning" -ForegroundColor Cyan
Write-Host "  • Device blocking" -ForegroundColor Cyan
Write-Host ""
Write-Host "If prompted, click 'Yes' to allow the application to run as Administrator." -ForegroundColor Red
Write-Host ""

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if ($isAdmin) {
    Write-Host "✅ Already running as Administrator" -ForegroundColor Green
    Write-Host "Starting DupeZ..." -ForegroundColor Green
    python run.py
} else {
    Write-Host "⚠️ Not running as Administrator" -ForegroundColor Yellow
    Write-Host "Elevating to Administrator privileges..." -ForegroundColor Yellow
    
    # Get the current script directory
    $scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
    
    # Start the application with administrator privileges
    Start-Process python -ArgumentList "run.py" -Verb RunAs -WorkingDirectory $scriptPath
    
    Write-Host ""
    Write-Host "✅ Application started with Administrator privileges." -ForegroundColor Green
    Write-Host "You can now use all features including the disconnect functionality." -ForegroundColor Green
}

Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") 