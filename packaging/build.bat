@echo off
setlocal

:: ── Run from repo root regardless of where this .bat lives ──────────
:: This script lives in packaging\. All downstream commands
:: (pip install -r requirements.txt, dist\dupez.exe paths, Inno Setup)
:: expect the cwd to be the repo root, so pushd one level up.
pushd "%~dp0.."

:: ── Version ─────────────────────────────────────────────────────────
:: Bump this ONE place per release. installer.iss and version_info.py
:: also carry their own copies (Inno Setup macro + PyInstaller version
:: resource respectively) — keep all three in sync.
set "DUPEZ_VERSION=5.7.9"
set "DUPEZ_INSTALLER=DupeZ_v%DUPEZ_VERSION%_Setup.exe"
set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\.venv\Scripts\python.exe"
set "DUPEZ_BUILD_VENV=%CD%\.build-venv"
set "DUPEZ_PYTHON=%DUPEZ_BUILD_VENV%\Scripts\python.exe"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PIP_REQUIRE_VIRTUALENV=true"
if not defined DUPEZ_SIGN_TIMESTAMP_URL set "DUPEZ_SIGN_TIMESTAMP_URL=http://timestamp.digicert.com"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Build Pipeline
echo ============================================
echo.

:: ── 1. Check prerequisites ──────────────────────────────────────────
if not exist "%DUPEZ_BOOTSTRAP_PYTHON%" (
    echo ERROR: Repository bootstrap interpreter not found:
    echo        %DUPEZ_BOOTSTRAP_PYTHON%
    echo Create .venv with 64-bit Python 3.11.9 and rerun this script.
    pause
    exit /b 1
)

"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 11, 9) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: Release builds require 64-bit Python 3.11.9.
    pause
    exit /b 1
)

if exist "%DUPEZ_BUILD_VENV%" rmdir /s /q "%DUPEZ_BUILD_VENV%"
if exist "%DUPEZ_BUILD_VENV%" (
    echo ERROR: Could not remove stale build environment:
    echo        %DUPEZ_BUILD_VENV%
    exit /b 1
)

echo Creating clean build-only virtual environment...
"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -m venv "%DUPEZ_BUILD_VENV%"
if errorlevel 1 exit /b 1
if not exist "%DUPEZ_PYTHON%" (
    echo ERROR: Build interpreter was not created:
    echo        %DUPEZ_PYTHON%
    exit /b 1
)

"%DUPEZ_PYTHON%" -I --version
if errorlevel 1 exit /b 1

echo Installing hash-pinned build tooling...
"%DUPEZ_PYTHON%" -I -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r packaging\requirements-build-locked.txt
if errorlevel 1 exit /b 1

:: ── 2. Install dependencies ─────────────────────────────────────────
echo Installing hash-pinned production dependencies...
"%DUPEZ_PYTHON%" -I -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements-locked.txt
if errorlevel 1 exit /b 1

echo Verifying hermetic build imports...
"%DUPEZ_PYTHON%" -I -c "import PyInstaller; import PyQt6.sip; from PyQt6 import QtCore, QtWidgets, QtWebEngineWidgets"
if errorlevel 1 (
    echo ERROR: Required build/runtime imports failed inside .build-venv.
    echo        Refusing to build with an incomplete or mixed Python environment.
    pause
    exit /b 1
)

:: ── 3. Build executable ─────────────────────────────────────────────
echo.
echo [1/4] Building dupez.exe ...
:: Remove stale exe so a failed build can't masquerade as success
if exist "dist\dupez.exe" del /q "dist\dupez.exe"
:: Invoke through the isolated build environment to avoid user-site drift.
"%DUPEZ_PYTHON%" -I -m PyInstaller packaging\dupez.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — PyInstaller returned an error.
    pause
    exit /b 1
)

if not exist "dist\dupez.exe" (
    echo.
    echo BUILD FAILED — dist\dupez.exe not produced.
    pause
    exit /b 1
)

echo       dupez.exe built successfully.
echo       Verifying frozen dependency boundary...
"%DUPEZ_PYTHON%" scripts\release_preflight.py --frozen-artifact dist\dupez.exe
if errorlevel 1 (
    echo.
    echo BUILD FAILED - dupez.exe contains forbidden optional dependencies.
    pause
    exit /b 1
)
echo       Frozen dependency boundary verified.

:: ── 4. Code signing (optional — skip if no cert) ────────────────────
echo.
echo [2/4] Code signing...

:: Check for signtool
set "_SIGNTOOL="
if defined DUPEZ_SIGNTOOL if exist "%DUPEZ_SIGNTOOL%" set "_SIGNTOOL=%DUPEZ_SIGNTOOL%"
if not defined _SIGNTOOL (
    where signtool >nul 2>&1 && set "_SIGNTOOL=signtool"
)
if not defined _SIGNTOOL (
    echo       signtool not found — skipping code signing.
    echo       To enable: install Windows SDK, then set DUPEZ_SIGN_CERT.
    goto :skip_sign
)

:: Check for signing certificate
if "%DUPEZ_SIGN_CERT%"=="" (
    echo       DUPEZ_SIGN_CERT not set — skipping code signing.
    echo       To enable: set DUPEZ_SIGN_CERT=path\to\certificate.pfx
    echo                  set DUPEZ_SIGN_PASS=your_password  ^(optional^)
    goto :skip_sign
)

echo       Signing dist\dupez.exe ...
if "%DUPEZ_SIGN_PASS%"=="" (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" dist\dupez.exe
) else (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" dist\dupez.exe
)

if errorlevel 1 (
    echo       WARNING: Signing failed. Continuing without signature.
) else (
    echo       Code signing complete.
)

:skip_sign

:: ── 5. Build installer (optional — skip if no ISCC) ────────────────
echo.
echo [3/4] Building installer...

where iscc >nul 2>&1
if errorlevel 1 (
    echo       Inno Setup ^(iscc^) not found -- skipping installer build.
    echo       To enable: install Inno Setup and add to PATH.
    goto :skip_installer
)

iscc packaging\installer.iss
if errorlevel 1 (
    echo       WARNING: Installer build failed.
    goto :skip_installer
)
echo       Installer built: dist\%DUPEZ_INSTALLER%

:: Emit the versionless installer alias after signing so both names are
:: byte-identical and carry the same Authenticode signature and timestamp.
:: This lets the landing page (and any external link) point at
:: https://github.com/GrihmLord/DupeZ/releases/latest/download/DupeZ_Setup.exe
:: forever without needing to re-edit the link every release. The versioned
:: copy (DupeZ_v%DUPEZ_VERSION%_Setup.exe) is still shipped for auditability
:: and as the canonical download in release notes.
:: Sign the installer too (flattened — batch can't handle triple-nested if-not blocks)
if not defined DUPEZ_SIGN_CERT goto :copy_installer_alias
if not defined _SIGNTOOL goto :copy_installer_alias
echo       Signing installer...
if defined DUPEZ_SIGN_PASS (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" dist\%DUPEZ_INSTALLER%
) else (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" dist\%DUPEZ_INSTALLER%
)
if errorlevel 1 (
    echo       ERROR: Authenticode signing failed for dist\%DUPEZ_INSTALLER%.
    exit /b 1
)

:copy_installer_alias
if exist "dist\%DUPEZ_INSTALLER%" (
    copy /Y "dist\%DUPEZ_INSTALLER%" "dist\DupeZ_Setup.exe" >nul
    if errorlevel 1 (
        echo       WARNING: Failed to create versionless alias dist\DupeZ_Setup.exe
    ) else (
        echo       Versionless alias: dist\DupeZ_Setup.exe
    )
)

:skip_installer

:: ── 6. Strip MOTW from raw exe (for direct distribution) ───────────
echo.
echo [4/4] Stripping Mark-of-the-Web from build output...

:: PowerShell one-liner to remove Zone.Identifier ADS
powershell -NoProfile -Command "Get-ChildItem 'dist' -Recurse | ForEach-Object { Unblock-File $_.FullName -ErrorAction SilentlyContinue }"
echo       MOTW stripped from dist\ contents.

:: ── Done ────────────────────────────────────────────────────────────
echo.
echo ============================================
echo  BUILD COMPLETE
echo ============================================
echo.
if exist "dist\%DUPEZ_INSTALLER%" (
    echo  Installer:  dist\%DUPEZ_INSTALLER%  [RECOMMENDED]
)
if exist "dist\DupeZ_Setup.exe" (
    echo  Alias:      dist\DupeZ_Setup.exe   [stable URL target]
)
echo  Portable:   dist\dupez.exe
echo.
echo  NOTE: For best Windows compatibility, distribute the
echo  installer (.exe Setup) rather than the raw portable exe.
echo  The installer strips MOTW and installs to Program Files,
echo  which avoids Application Control / SmartScreen blocks.
echo.
echo  For zero SmartScreen warnings, code-sign with:
echo    set DUPEZ_SIGN_CERT=path
