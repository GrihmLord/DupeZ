# DupeZ Administrator Launcher (PowerShell)
# This script launches DupeZ with administrator privileges

Write-Host "DupeZ Administrator Launcher" -ForegroundColor Cyan
Write-Host "============================" -ForegroundColor Cyan
Write-Host ""

Write-Host "This script will launch DupeZ with administrator privileges" -ForegroundColor Yellow
Write-Host "which are required for network disruption features to work." -ForegroundColor Yellow
Write-Host ""

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if ($isAdmin) {
    Write-Host "✓ Already running as administrator" -ForegroundColor Green
    Write-Host "Launching DupeZ..." -ForegroundColor Green
    
    # Check if Python is available
    try {
        $pythonVersion = python --version 2>&1
        Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
        
        # Launch DupeZ
        Set-Location $PSScriptRoot
        python run.py
        
    } catch {
        Write-Host "✗ Error: Python not found or not accessible" -ForegroundColor Red
        Write-Host "Please ensure Python is installed and in your PATH" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    
} else {
    Write-Host "✗ Not running as administrator" -ForegroundColor Red
    Write-Host "Elevating privileges..." -ForegroundColor Yellow
    
    try {
        # Relaunch with admin privileges
        Start-Process PowerShell -ArgumentList "-File `"$PSCommandPath`"" -Verb RunAs
    } catch {
        Write-Host "✗ Failed to elevate privileges" -ForegroundColor Red
        Write-Host "Please run this script as administrator manually" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}
