@echo off
setlocal

:: ── Run from repo root regardless of where this .bat lives ──────────
:: This script lives in packaging\. All downstream commands expect
:: repo root as cwd (requirements.txt, dist\, build\ dirs).
pushd "%~dp0.."

:: ── DupeZ variant build pipeline ────────────────────────────────────
:: Produces both user-facing builds:
::
::   dist\DupeZ-GPU.exe     — asInvoker, split-arch, GPU map
::   dist\DupeZ-Compat.exe  — requireAdministrator, inproc, legacy
::
:: Run from the repo root:
::     build_variants.bat
::
:: Prereqs: python, PyInstaller, everything in requirements.txt.

set "DUPEZ_VERSION=5.6.1"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Variant Build
echo ============================================
echo.

:: ── 1. Prereqs ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Installing dependencies...
pip install -r requirements.txt

:: ── 2. Clean stale artifacts ────────────────────────────────────────
if exist "dist\DupeZ-GPU.exe"    del /q "dist\DupeZ-GPU.exe"
if exist "dist\DupeZ-Compat.exe" del /q "dist\DupeZ-Compat.exe"
if exist "build\DupeZ-GPU"       rmdir /s /q "build\DupeZ-GPU"
if exist "build\DupeZ-Compat"    rmdir /s /q "build\DupeZ-Compat"

:: ── 3. Build GPU variant (asInvoker + split) ────────────────────────
echo.
echo [1/3] Building DupeZ-GPU.exe ...
python -m PyInstaller packaging\dupez_gpu.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — DupeZ-GPU PyInstaller returned an error.
    pause
    exit /b 1
)
if not exist "dist\DupeZ-GPU.exe" (
    echo.
    echo BUILD FAILED — dist\DupeZ-GPU.exe not produced.
    pause
    exit /b 1
)
echo       DupeZ-GPU.exe built successfully.

:: ── 4. Build Compat variant (requireAdministrator + inproc) ─────────
echo.
echo [2/3] Building DupeZ-Compat.exe ...
python -m PyInstaller packaging\dupez_compat.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — DupeZ-Compat PyInstaller returned an error.
    pause
    exit /b 1
)
if not exist "dist\DupeZ-Compat.exe" (
    echo.
    echo BUILD FAILED — dist\DupeZ-Compat.exe not produced.
    pause
    exit /b 1
)
echo       DupeZ-Compat.exe built successfully.

:: ── 5. Strip MOTW from raw exes ─────────────────────────────────────
echo.
echo [3/3] Stripping Mark-of-the-Web from build output...
powershell -NoProfile -Command "Get-ChildItem 'dist' -Recurse | ForEach-Object { Unblock-File $_.FullName -ErrorAction SilentlyContinue }"
echo       MOTW stripped from dist\ contents.

echo.
echo ============================================
echo  VARIANT BUILD COMPLETE
echo ============================================
echo.
echo   dist\DupeZ-GPU.exe     ^(asInvoker, split, GPU map — RECOMMENDED^)
echo   dist\DupeZ-Compat.exe  ^(requireAdministrator, inproc, legacy^)
echo.
echo  Ship BOTH on the release page. GPU is the default download;
echo  Co
