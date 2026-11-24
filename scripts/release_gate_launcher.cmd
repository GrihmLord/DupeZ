@echo off
setlocal
cd /d "%~dp0.."

set VERSION=5.8.0

echo ============================================
echo  DupeZ Blocked Release Gates Launcher
echo ============================================
echo.
echo This shows release status by default.
echo Pass a named -Phase explicitly to advance a release gate.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\release.ps1" -Version %VERSION% %*
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
