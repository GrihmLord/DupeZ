@echo off
REM DupeZ Admin Launcher
REM Run DupeZ with administrator privileges

echo Requesting administrator privileges...
echo.

REM Check if running as admin
net session >nul 2>&1
if errorlevel 1 (
    echo This script requires administrator privileges.
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

echo Administrator privileges confirmed.
echo Starting DupeZ with admin rights...
echo.

REM Start DupeZ
python run.py

echo.
echo DupeZ has exited.
pause 