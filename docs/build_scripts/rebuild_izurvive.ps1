# DupeZ iZurvive Map Integration Rebuild Script
# Run as Administrator for best results

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DupeZ iZurvive Map Integration Rebuild" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/5] Installing WebEngine dependencies..." -ForegroundColor Yellow
pip install -r requirements_webengine.txt

Write-Host ""
Write-Host "[2/5] Cleaning previous build..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "__pycache__") { Remove-Item "__pycache__" -Recurse -Force }
if (Test-Path "*.spec") { Remove-Item "*.spec" -Force }

Write-Host ""
Write-Host "[3/5] Building application with iZurvive..." -ForegroundColor Yellow
pyinstaller --onefile --windowed --icon=app/assets/icon.ico --name=DupeZ_izurvive app/main.py

Write-Host ""
Write-Host "[4/5] Copying additional files..." -ForegroundColor Yellow
if (-not (Test-Path "dist\DupeZ_izurvive")) { New-Item -ItemType Directory -Path "dist\DupeZ_izurvive" -Force }
Copy-Item "app\assets" "dist\DupeZ_izurvive\app\assets" -Recurse -Force
Copy-Item "app\config" "dist\DupeZ_izurvive\app\config" -Recurse -Force

Write-Host ""
Write-Host "[5/5] Build complete!" -ForegroundColor Green
Write-Host ""
Write-Host "The new DupeZ application with iZurvive integration is ready!" -ForegroundColor Green
Write-Host "Location: dist\DupeZ_izurvive.exe" -ForegroundColor Cyan
Write-Host ""
Write-Host "Features:" -ForegroundColor Yellow
Write-Host "- Full iZurvive DayZ map integration" -ForegroundColor White
Write-Host "- Interactive map controls" -ForegroundColor White
Write-Host "- GPS coordinate system" -ForegroundColor White
Write-Host "- Marker management" -ForegroundColor White
Write-Host "- Export/Import functionality" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to continue..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
