@echo off
echo DupeZ Administrator Launcher
echo ============================
echo.
echo This script will launch DupeZ with administrator privileges
echo which are required for network disruption features to work.
echo.
echo Press any key to continue...
pause >nul

echo.
echo Launching DupeZ with administrator privileges...
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again.
    pause
    exit /b 1
)

REM Launch DupeZ with admin privileges
powershell -Command "Start-Process python -ArgumentList 'run.py' -Verb RunAs -WorkingDirectory '%~dp0'"

echo.
echo DupeZ launched with administrator privileges.
echo Network disruption features should now work properly.
echo.
pause
