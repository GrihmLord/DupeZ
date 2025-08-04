@echo off
echo ========================================
echo    WinDivert Installation for DupeZ
echo ========================================
echo.

echo Checking WinDivert availability...
python check_windivert_status.py

if %errorlevel% equ 0 (
    echo.
    echo WinDivert is already installed and working!
    pause
    exit /b 0
)

echo.
echo WinDivert is not installed. Attempting download...
echo.

python download_windivert_manual.py

if %errorlevel% equ 0 (
    echo.
    echo WinDivert installation completed successfully!
    echo.
    echo Verifying installation...
    python check_windivert_status.py
) else (
    echo.
    echo Automatic download failed.
    echo.
    echo Manual installation required:
    echo 1. Visit: https://reqrypt.org/windivert.html
    echo 2. Download WinDivert for your system
    echo 3. Extract and copy WinDivert64.exe to this directory
    echo 4. Run this script again
)

echo.
pause 