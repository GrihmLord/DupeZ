# DupeZ Launch Script
# Advanced Network Control with iZurvive DayZ Integration

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "🚀 DupeZ - Advanced Network Control" -ForegroundColor Cyan
Write-Host "🗺️  with iZurvive DayZ Integration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Launching DupeZ application..." -ForegroundColor Yellow
Write-Host ""

$executablePath = "dist\DupeZ_izurvive.exe"

if (Test-Path $executablePath) {
    Write-Host "✅ Found DupeZ executable" -ForegroundColor Green
    Write-Host "🚀 Starting application..." -ForegroundColor Green
    Start-Process $executablePath
} else {
    Write-Host "❌ DupeZ executable not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please build the application first:" -ForegroundColor Yellow
    Write-Host "1. Run: docs\build_scripts\rebuild_izurvive.ps1" -ForegroundColor White
    Write-Host "2. Then run this script again" -ForegroundColor White
    Write-Host ""
    Write-Host "Press any key to continue..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
