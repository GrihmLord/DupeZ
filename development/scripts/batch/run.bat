@echo off
REM DupeZ Launcher Batch File
REM Run this to start DupeZ with proper environment

echo Starting DupeZ...
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ and try again
    pause
    exit /b 1
)

REM Check if required files exist
if not exist "run.py" (
    echo ERROR: run.py not found
    echo Please run this from the DupeZ project directory
    pause
    exit /b 1
)

REM Start DupeZ
echo Launching DupeZ...
python run.py

REM Check if DupeZ started successfully
if errorlevel 1 (
    echo.
    echo DupeZ encountered an error. Check the logs for details.
    pause
) else (
    echo.
    echo DupeZ has exited normally.
) 