@echo off
echo ============================================
echo  DupeZ Build Script
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

:: Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

:: Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Building dupez.exe ...
pyinstaller dupez.spec --noconfirm

if exist "dist\dupez.exe" (
    echo.
    echo ============================================
    echo  BUILD SUCCESS
    echo  Output: dist\dupez.exe
    echo ============================================
) else (
    echo.
    echo BUILD FAILED — check output above for errors.
)

pause
