@echo off
setlocal

:: Legacy compatibility build only. Public release artifacts must be built by
:: packaging\build_variants.bat and the protected release finalizer.
pushd "%~dp0.." >nul
if errorlevel 1 (
    echo ERROR: Could not enter the repository root.
    endlocal & exit /b 1
)

set "DUPEZ_EXIT_CODE=1"

:: ── Version ─────────────────────────────────────────────────────────
:: Keep this version synchronized even though this is not a release path.
set "DUPEZ_VERSION=5.8.0"
if not defined DUPEZ_BOOTSTRAP_PYTHON set "DUPEZ_BOOTSTRAP_PYTHON=%CD%\.venv\Scripts\python.exe"
set "DUPEZ_BUILD_VENV=%CD%\.release-venv"
set "DUPEZ_PYTHON=%DUPEZ_BUILD_VENV%\Scripts\python.exe"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONHASHSEED=0"
:: ZIP-based Windows launchers cannot represent timestamps before 1980.
set "SOURCE_DATE_EPOCH=315532800"
set "PIP_REQUIRE_VIRTUALENV=true"
if not defined DUPEZ_SIGN_TIMESTAMP_URL set "DUPEZ_SIGN_TIMESTAMP_URL=http://timestamp.digicert.com"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Legacy Portable Build
echo  NON-RELEASE: emits only dist\dupez.exe
echo ============================================
echo.

if not exist "%DUPEZ_BOOTSTRAP_PYTHON%" (
    echo ERROR: Repository bootstrap interpreter not found:
    echo        %DUPEZ_BOOTSTRAP_PYTHON%
    echo Create .venv with 64-bit Python 3.13.17 and rerun this script.
    goto :fail
)

"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 13, 17) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: This build requires 64-bit Python 3.13.17.
    goto :fail
)

if exist "%DUPEZ_BUILD_VENV%" rmdir /s /q "%DUPEZ_BUILD_VENV%"
if exist "%DUPEZ_BUILD_VENV%" (
    echo ERROR: Could not remove stale build environment:
    echo        %DUPEZ_BUILD_VENV%
    goto :fail
)

echo Creating clean build-only virtual environment...
"%DUPEZ_BOOTSTRAP_PYTHON%" -I -S -m venv "%DUPEZ_BUILD_VENV%"
if errorlevel 1 goto :fail
if not exist "%DUPEZ_PYTHON%" (
    echo ERROR: Build interpreter was not created:
    echo        %DUPEZ_PYTHON%
    goto :fail
)

"%DUPEZ_PYTHON%" -I --version
if errorlevel 1 goto :fail

echo Installing hash-pinned build tooling...
"%DUPEZ_PYTHON%" -I -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r packaging\requirements-build-locked.txt
if errorlevel 1 goto :fail

echo Installing hash-pinned production dependencies...
"%DUPEZ_PYTHON%" -I -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements-locked.txt
if errorlevel 1 goto :fail

echo Verifying hermetic build imports...
"%DUPEZ_PYTHON%" -I -c "import PyInstaller; import PyQt6.sip; from PyQt6 import QtCore, QtWidgets, QtNetwork"
if errorlevel 1 (
    echo ERROR: Required build/runtime imports failed inside .release-venv.
    echo        Refusing to build with an incomplete or mixed Python environment.
    goto :fail
)

echo.
echo [1/3] Building legacy portable dist\dupez.exe ...
:: Remove stale exe so a failed build can't masquerade as success
if exist "dist\dupez.exe" del /q "dist\dupez.exe"
if exist "dist\dupez.exe" (
    echo ERROR: Could not remove stale dist\dupez.exe.
    goto :fail
)
:: Invoke through the isolated build environment to avoid user-site drift.
"%DUPEZ_PYTHON%" -I -m PyInstaller packaging\dupez.spec --noconfirm
if errorlevel 1 (
    echo.
    echo BUILD FAILED — PyInstaller returned an error.
    goto :fail
)

if not exist "dist\dupez.exe" (
    echo.
    echo BUILD FAILED — dist\dupez.exe not produced.
    goto :fail
)

echo       dupez.exe built successfully.
echo       Verifying frozen dependency boundary...
"%DUPEZ_PYTHON%" scripts\release_preflight.py --frozen-artifact dist\dupez.exe
if errorlevel 1 (
    echo.
    echo BUILD FAILED - dupez.exe contains forbidden optional dependencies.
    goto :fail
)
echo       Legacy portable dependency boundary verified.

echo.
echo [2/3] Applying optional Authenticode signature ...

:: Check for signtool
set "_SIGNTOOL="
if defined DUPEZ_SIGNTOOL if exist "%DUPEZ_SIGNTOOL%" set "_SIGNTOOL=%DUPEZ_SIGNTOOL%"
if not defined _SIGNTOOL (
    where signtool >nul 2>&1 && set "_SIGNTOOL=signtool"
)
if not defined _SIGNTOOL (
    echo       signtool not found -- leaving the local portable unsigned.
    goto :skip_sign
)

:: Check for signing certificate
if not defined DUPEZ_SIGN_CERT (
    echo       DUPEZ_SIGN_CERT not set -- leaving the local portable unsigned.
    goto :skip_sign
)

echo       Signing dist\dupez.exe ...
if "%DUPEZ_SIGN_PASS%"=="" (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" dist\dupez.exe
) else (
    "%_SIGNTOOL%" sign /tr "%DUPEZ_SIGN_TIMESTAMP_URL%" /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" dist\dupez.exe
)

if errorlevel 1 (
    echo       WARNING: Optional signing failed; the local portable remains non-release.
) else (
    echo       Local portable signing complete.
)

:skip_sign
echo.
echo [3/3] Removing Mark-of-the-Web from dist\dupez.exe only ...
powershell -NoProfile -Command "Unblock-File -LiteralPath 'dist\dupez.exe' -ErrorAction SilentlyContinue"
if errorlevel 1 (
    echo       WARNING: Could not remove Mark-of-the-Web from dist\dupez.exe.
)

echo.
echo ============================================
echo  LEGACY PORTABLE BUILD COMPLETE
echo ============================================
echo  Output: dist\dupez.exe
echo  This file is not a release-approved artifact.
echo  Canonical releases use packaging\build_variants.bat.
echo.
goto :success

:fail
set "DUPEZ_EXIT_CODE=1"
goto :finish

:success
set "DUPEZ_EXIT_CODE=0"

:finish
popd
endlocal & exit /b %DUPEZ_EXIT_CODE%
