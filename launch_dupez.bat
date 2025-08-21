@echo off
echo ========================================
echo 🚀 DupeZ - Advanced Network Control
echo 🗺️  with iZurvive DayZ Integration
echo ========================================
echo.

echo Launching DupeZ application...
echo.

if exist "dist\DupeZ_izurvive.exe" (
    echo ✅ Found DupeZ executable
    echo 🚀 Starting application...
    start "" "dist\DupeZ_izurvive.exe"
) else (
    echo ❌ DupeZ executable not found
    echo.
    echo Please build the application first:
    echo 1. Run: docs\build_scripts\rebuild_izurvive.bat
    echo 2. Then run this script again
    echo.
    pause
)
