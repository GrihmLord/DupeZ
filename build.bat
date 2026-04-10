@echo off
setlocal

:: ── Version ─────────────────────────────────────────────────────────
:: Bump this ONE place per release. installer.iss and version_info.py
:: also carry their own copies (Inno Setup macro + PyInstaller version
:: resource respectively) — keep all three in sync.
set "DUPEZ_VERSION=5.2.2"
set "DUPEZ_INSTALLER=DupeZ_v%DUPEZ_VERSION%_Setup.exe"

echo ============================================
echo  DupeZ v%DUPEZ_VERSION% -- Build Pipeline
echo ============================================
echo.

:: ── 1. Check prerequisites ──────────────────────────────────────────
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

:: ── 2. Install dependencies ─────────────────────────────────────────
echo Installing dependencies...
pip install -r requirements.txt

:: ── 3. Build executable ─────────────────────────────────────────────
echo.
echo [1/4] Building dupez.exe ...
:: Remove stale exe so a failed build can't masquerade as success
if exist "dist\dupez.exe" del /q "dist\dupez.exe"
:: Invoke via `python -m` to avoid PATH issues with user-site Scripts dir
python -m PyInstaller dupez.spec --noconfirm
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

:: ── 4. Code signing (optional — skip if no cert) ────────────────────
echo.
echo [2/4] Code signing...

:: Check for signtool
where signtool >nul 2>&1
if errorlevel 1 (
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
    signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" dist\dupez.exe
) else (
    signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" dist\dupez.exe
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

iscc installer.iss
if errorlevel 1 (
    echo       WARNING: Installer build failed.
    goto :skip_installer
)
echo       Installer built: dist\%DUPEZ_INSTALLER%

:: Sign the installer too (flattened — batch can't handle triple-nested if-not blocks)
if not defined DUPEZ_SIGN_CERT goto :skip_installer
where signtool >nul 2>&1
if errorlevel 1 goto :skip_installer
echo       Signing installer...
if defined DUPEZ_SIGN_PASS (
    signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" /p "%DUPEZ_SIGN_PASS%" dist\%DUPEZ_INSTALLER%
) else (
    signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /f "%DUPEZ_SIGN_CERT%" dist\%DUPEZ_INSTALLER%
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
echo  Portable:   dist\dupez.exe
echo.
echo  NOTE: For best Windows compatibility, distribute the
echo  installer (.exe Setup) rather than the raw portable exe.
echo  The installer strips MOTW and installs to Program Files,
echo  which avoids Application Control / SmartScreen blocks.
echo.
echo  For zero SmartScreen warnings, code-sign with:
echo    set DUPEZ_SIGN_CE