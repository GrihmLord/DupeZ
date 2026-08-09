@echo off
setlocal
cd /d "%~dp0.."

set VERSION=5.8.0

echo ============================================
echo  DupeZ Blocked Release Gates Launcher
echo ============================================
echo.
echo This will run the next blocked gate phase and track progress.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\release_gate_launcher.ps1" -Phase auto -Version %VERSION%
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% EQU 0 (
  echo Launcher completed successfully.
) else (
  echo Launcher failed with exit code %EXITCODE%.
)

echo.
pause
exit /b %EXITCODE%
