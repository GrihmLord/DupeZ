@echo off
REM DupeZ Admin Launcher - Ensures Virtual Environment Usage
REM This script guarantees the same Python environment is used regardless of admin privileges

echo Starting DupeZ with Admin Privileges and Virtual Environment...

REM Change to the DupeZ directory
cd /d "%~dp0"

REM Activate virtual environment
call ".venv\Scripts\activate.bat"

REM Verify we're using the correct Python
echo Using Python: 
python -c "import sys; print(sys.executable)"

REM Run DupeZ
echo.
echo Starting DupeZ Application...
python -m app.main

REM Keep window open if there's an error
if errorlevel 1 (
    echo.
    echo Application exited with error code %errorlevel%
    pause
)
