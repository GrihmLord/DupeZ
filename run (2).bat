@echo off
echo 🚀 DupeZ - GUI Launcher
echo ================================================
echo.
echo Starting DupeZ GUI application...
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ and try again
    pause
    exit /b 1
)

REM Check if required packages are installed
python -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install -r requirements.txt
)

REM Launch the application
echo Launching DupeZ...
python run.py

echo.
echo Application closed.
pause 