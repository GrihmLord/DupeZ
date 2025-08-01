@echo off
echo Starting PulseDrop Pro - Advanced LagSwitch Tool...
echo.

REM Check if executable exists
if not exist "dist\PulseDropPro.exe" (
    echo ERROR: PulseDropPro.exe not found in dist folder!
    echo Please build the executable first using: python -m PyInstaller PulseDropPro.spec
    pause
    exit /b 1
)

REM Run the executable
echo Launching PulseDrop Pro...
start "" "dist\PulseDropPro.exe"

echo.
echo PulseDrop Pro is starting...
echo If the application doesn't start, check the logs folder for error messages.
pause 