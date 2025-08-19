@echo off
title DupeZ Admin Launcher
echo.
echo ========================================
echo     DupeZ v2.0.0 Professional Edition
echo     Admin Launcher with Environment Fix
echo ========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Check if virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found!
    echo Please ensure .venv directory exists in the DupeZ folder.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call ".venv\Scripts\activate.bat"

REM Show environment info
echo.
echo Environment Information:
python -c "import sys, os; print(f'Python: {sys.executable}'); print(f'Directory: {os.getcwd()}'); import ctypes; print(f'Admin: {bool(ctypes.windll.shell32.IsUserAnAdmin())}')"
echo.

REM Start DupeZ
echo Starting DupeZ Application...
echo Window title will show [ADMIN] when running with admin privileges
echo.
python -m app.main

REM Keep window open if there's an error
if errorlevel 1 (
    echo.
    echo Application exited with error code %errorlevel%
    pause
)
