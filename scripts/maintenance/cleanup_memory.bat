@echo off
echo ========================================
echo    DupeZ Maintenance & Cleanup Utility
echo ========================================
echo.
echo This utility helps maintain optimal performance for DupeZ
echo Run this before launching DupeZ if you experience issues
echo.

echo 🧹 Cleaning up temporary files...
if exist "%TEMP%\dupez_*" (
    del /q "%TEMP%\dupez_*" 2>nul
    echo    Temporary files cleaned
) else (
    echo    No temporary files found
)

echo.
echo 🗑️  Cleaning up old log files...
if exist "logs\*.log.*" (
    del /q "logs\*.log.*" 2>nul
    echo    Old log files cleaned
) else (
    echo    No old log files found
)

echo.
echo 📁 Checking disk space...
for /f "tokens=3" %%a in ('dir /-c 2^>nul ^| find "bytes free"') do set free_space=%%a
echo    Available disk space: %free_space%

echo.
echo 💾 Checking memory usage...
wmic OS get FreePhysicalMemory /value | find "FreePhysicalMemory=" > temp_mem.txt
for /f "tokens=2 delims==" %%a in (temp_mem.txt) do set free_mem=%%a
del temp_mem.txt
set /a free_mem_mb=%free_mem% / 1024
echo    Available memory: %free_mem_mb% MB

echo.
echo 🔄 Clearing Windows temp and cache...
del /q /s "%TEMP%\*" 2>nul
del /q /s "%LOCALAPPDATA%\Temp\*" 2>nul
echo    Windows cache cleared

echo.
echo ✅ Maintenance cleanup completed!
echo.
echo 🚀 DupeZ is ready to run with optimized performance
echo    Use 'python run.py' to launch the application
echo.
pause
