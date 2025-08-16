@echo off
REM WinDivert Installation Script
REM Installs WinDivert for DupeZ network features

echo DupeZ WinDivert Installer
echo ==========================
echo.

REM Check for admin privileges
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Administrator privileges required
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

echo Administrator privileges confirmed.
echo Installing WinDivert...
echo.

REM Check if WinDivert is already installed
if exist "C:\Windows\System32\WinDivert.dll" (
    echo WinDivert is already installed.
    echo Checking version...
    echo.
) else (
    echo WinDivert not found. Installing...
    echo.
)

REM Copy WinDivert files
echo Copying WinDivert files...
if exist "temp_windivert\WinDivert.dll" (
    copy "temp_windivert\WinDivert.dll" "C:\Windows\System32\" >nul
    echo - WinDivert.dll copied
) else (
    echo WARNING: WinDivert.dll not found in temp_windivert\
)

if exist "temp_windivert\WinDivert64.sys" (
    copy "temp_windivert\WinDivert64.sys" "C:\Windows\System32\drivers\" >nul
    echo - WinDivert64.sys copied
) else (
    echo WARNING: WinDivert64.sys not found in temp_windivert\
)

echo.
echo WinDivert installation completed.
echo DupeZ can now use advanced network features.
echo.
pause 